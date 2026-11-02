"""Explicit service delegation: manager authorizes; worker executes locally.

The Unix endpoint never executes checkout code. The worker does not open the
registry. Protect each grant's credentials, runtime root and socket with the
caller's sandbox; capabilities are not a replacement for OS isolation.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lodex_core.management import services, worktrees
from lodex_core.management.common import ManagementError, now, private_dir, write_private
from lodex_core.management.environment import inputs
from lodex_core.management.project_config import CONFIG, load
from lodex_core.management.store import Registry

ENVIRONMENT = "LODEX_SERVICE_DELEGATION"
KIND = "service-delegation"
VERSION = 1
MAX_MESSAGE = 1024 * 1024
ACTIONS = {"start", "stop", "list", "inspect", "logs"}


def receive(connection: socket.socket) -> dict[str, Any]:
    data = bytearray()
    while b"\n" not in data:
        chunk = connection.recv(min(65536, MAX_MESSAGE + 1 - len(data)))
        if not chunk:
            raise ManagementError("invalid_request", "Incomplete delegation message")
        data.extend(chunk)
        if len(data) > MAX_MESSAGE:
            raise ManagementError("invalid_request", "Delegation message is too large")
    if data[-1:] != b"\n" or data.count(b"\n") != 1:
        raise ManagementError("invalid_request", "Expected one delegation message")
    try:
        value = json.loads(data)
    except (ValueError, RecursionError) as exc:
        raise ManagementError("invalid_request", "Expected delegation JSON") from exc
    if not isinstance(value, dict):
        raise ManagementError("invalid_request", "Expected a delegation object")
    return value


def send(connection: socket.socket, value: dict[str, Any]) -> None:
    data = json.dumps(value).encode() + b"\n"
    if len(data) > MAX_MESSAGE:
        raise ManagementError("invalid_request", "Delegation response is too large")
    connection.sendall(data)


def revoke(registry: Registry, identity: str) -> dict[str, Any]:
    grant = registry.get(KIND, identity)
    with registry.lock(grant["taskenv"]):
        grant = registry.get(KIND, identity)
        grant.update(active=False, observed_at=now())
        registry.put(KIND, grant)
    return {"id": identity, "taskenv": grant["taskenv"], "active": False}


class Controller:
    """One foreground, single-task manager endpoint; no automatic daemon/retry."""

    def __init__(self, registry: Registry, task: dict[str, Any], names: list[str]) -> None:
        self.registry = registry
        self.task = dict(task)
        self.names = sorted(set(names))
        self.token = secrets.token_urlsafe(32)
        self.identity = uuid.uuid4().hex
        self.socket: socket.socket | None = None
        self.socket_inode: tuple[int, int] | None = None
        self.closed = False
        with registry.lock(task["id"]):
            registry.reload_task(self.task)
            worktrees.require_present(self.task)
            self.config, _, _ = inputs(registry, self.task, secrets=False)
            if not self.names or set(self.names) - self.config["services"].keys():
                raise ManagementError("delegation_scope", "Select configured services explicitly")
            if any(
                grant["taskenv"] == task["id"] and grant["active"] for grant in registry.all(KIND)
            ):
                raise ManagementError("delegation_active", "Revoke the existing delegation first")
            root = registry.root / "delegated" / self.identity[:12]
            endpoint = registry.root / "delegation-sockets" / f"{self.identity[:12]}.sock"
            # Leave room for the per-launch service socket too (macOS sun_path).
            if len(os.fsencode(endpoint)) > 100 or len(os.fsencode(root)) + 20 > 100:
                raise ManagementError("socket_path_long", "Use a shorter Lodex state root")
            private_dir(root.parent)
            root.mkdir(mode=0o700)
            observed = root.stat()
            self.runtime: dict[str, Any] = {
                "grant": self.identity,
                "root": str(root),
                "inode": [observed.st_dev, observed.st_ino],
            }
            private_dir(endpoint.parent)
            self.endpoint = endpoint
            self.credential_file = root / "client.json"
            try:
                self.socket = socket.socket(socket.AF_UNIX)
                self.socket.bind(str(endpoint))
                endpoint.chmod(0o600)
                observed = endpoint.stat()
                self.socket_inode = (observed.st_dev, observed.st_ino)
                self.socket.listen(8)
                self.socket.settimeout(0.2)
                write_private(
                    self.credential_file,
                    json.dumps(
                        {
                            "version": VERSION,
                            "id": self.identity,
                            "token": self.token,
                            "socket": str(endpoint),
                            "taskenv": self.task["id"],
                            "path": self.task["path"],
                            "runtime_root": str(root),
                        }
                    ),
                )
                registry.put(
                    KIND,
                    {
                        "id": self.identity,
                        "taskenv": self.task["id"],
                        "active": True,
                        "services": self.names,
                        "socket": str(endpoint),
                        "runtime_root": str(root),
                        "created_at": now(),
                        "observed_at": now(),
                    },
                )
            except BaseException:
                if self.socket is not None:
                    self.socket.close()
                self._unlink_socket()
                raise

    def info(self) -> dict[str, Any]:
        return {
            "id": self.identity,
            "taskenv": self.task["id"],
            "services": self.names,
            "socket": str(self.endpoint),
            "credential_file": str(self.credential_file),
            "runtime_root": self.runtime["root"],
            "state": "listening",
        }

    def _unlink_socket(self) -> None:
        try:
            observed = self.endpoint.lstat()
            if (observed.st_dev, observed.st_ino) == self.socket_inode:
                self.endpoint.unlink()
        except FileNotFoundError:
            pass

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.socket is not None:
            self.socket.close()
        self._unlink_socket()
        # Keep runtime observations and central control handles for manager takeover.
        revoke(self.registry, self.identity)

    def _verify(self) -> None:
        if self.closed or not self.registry.get(KIND, self.identity)["active"]:
            raise ManagementError("delegation_revoked", "Service delegation is inactive")
        current = self.registry.get("taskenv", self.task["id"])
        for key in ("path", "common", "git_dir", "inode", "common_inode", "git_inode"):
            if current.get(key) != self.task.get(key):
                raise ManagementError("identity_changed", "Delegated taskenv identity changed")
        worktrees.require_present(current)
        descriptor = os.open(self.runtime["root"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            observed = os.fstat(descriptor)
            if [observed.st_dev, observed.st_ino] != self.runtime["inode"]:
                raise ManagementError("identity_changed", "Delegated runtime root was replaced")
        finally:
            os.close(descriptor)

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        token = request.get("token")
        if not isinstance(token, str) or not hmac.compare_digest(
            token.encode(), self.token.encode()
        ):
            raise ManagementError("unauthorized", "Invalid delegation credential")
        action = request.get("action")
        if (
            type(request.get("version")) is not int
            or request["version"] != VERSION
            or set(request) - {"version", "token", "action", "target", "service", "launch"}
            or not isinstance(action, str)
            or action not in ACTIONS
        ):
            raise ManagementError("delegation_scope", "Unsupported delegation request")
        target = request.get("target")
        if target is not None:
            if not isinstance(target, str):
                raise ManagementError("delegation_scope", "Invalid taskenv selector")
            if target != self.task["id"]:
                path = Path(target)
                root = Path(self.task["path"])
                if not path.is_absolute() or not path.resolve().is_relative_to(root):
                    raise ManagementError("delegation_scope", "Target is outside this delegation")
                if worktrees.resolve(self.registry, target)["id"] != self.task["id"]:
                    raise ManagementError("delegation_scope", "Target is outside this delegation")
        name = request.get("service")
        if action != "list" and (not isinstance(name, str) or name not in self.names):
            raise ManagementError("delegation_scope", "Service is outside this delegation")
        if action == "list" and name is not None:
            raise ManagementError("delegation_scope", "List does not accept a service selector")
        service_name = name if isinstance(name, str) else ""
        with self.registry.lock(self.task["id"]):
            self._verify()
            if action != "list":
                assert isinstance(name, str)
            if action == "start":
                if load(Path(self.task["path"]) / CONFIG) != self.config:
                    raise ManagementError(
                        "delegation_config_changed", "Recipe changed; request a new delegation"
                    )
                record, payload = services.prepare_start(
                    self.registry,
                    self.task,
                    service_name,
                    runtime=self.runtime,
                    configuration=self.config,
                )
                return {
                    "record": services.with_pending_acks(self.registry, record),
                    "payload": payload,
                }
            if action == "list":
                return {
                    "services": [
                        record
                        for record in services.list_services(self.registry, self.task["id"])
                        if record["name"] in self.names
                    ]
                }
            record = self.registry.get("service", f"{self.task['id']}-{name}")
            if "launch" in request and request["launch"] != record.get("delegated", {}).get(
                "launch"
            ):
                raise ManagementError("stale_launch", "Service launch was replaced; inspect it")
            if action == "stop":
                return services.stop_locked(self.registry, self.task["id"], service_name)
            if action == "logs":
                return services.logs(self.registry, self.task["id"], service_name)
            return services.record_observation(self.registry, services.refresh(record))

    def serve(self, ready: Callable[[dict[str, Any]], object]) -> None:
        assert self.socket is not None
        try:
            ready(self.info())
            while self.registry.get(KIND, self.identity)["active"]:
                try:
                    connection, _ = self.socket.accept()
                except TimeoutError:
                    continue
                with connection:
                    connection.settimeout(1)
                    try:
                        result = self.dispatch(receive(connection))
                        response = {"ok": True, "result": result}
                    except ManagementError as exc:
                        response = {"ok": False, "error": exc.as_dict()}
                    except (OSError, ValueError):
                        response = {
                            "ok": False,
                            "error": {
                                "code": "delegation_io",
                                "message": "Cannot verify delegated service data",
                            },
                        }
                    try:
                        try:
                            send(connection, response)
                        except ManagementError as exc:
                            send(connection, {"ok": False, "error": exc.as_dict()})
                    except OSError:
                        pass
        finally:
            self.close()


class Client:
    def __init__(self, path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise ManagementError(
                "invalid_credential", "Delegation credential must be a regular file"
            )
        try:
            credential = json.loads(path.read_text())
            if (
                not isinstance(credential, dict)
                or type(credential.get("version")) is not int
                or credential["version"] != VERSION
                or not all(
                    isinstance(credential.get(key), str) and credential[key]
                    for key in ("socket", "token", "taskenv", "path", "runtime_root")
                )
            ):
                raise ValueError
        except (OSError, ValueError, RecursionError) as exc:
            raise ManagementError(
                "invalid_credential", "Cannot read service delegation credential"
            ) from exc
        self.credential = credential

    def request(
        self,
        action: str,
        name: str | None = None,
        target: str | None = None,
        *,
        launch: str | None = None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "version": VERSION,
            "token": self.credential["token"],
            "action": action,
            "target": target,
            "service": name,
        }
        if launch is not None:
            request["launch"] = launch
        try:
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(310)
                connection.connect(self.credential["socket"])
                send(connection, request)
                response = receive(connection)
        except (OSError, ValueError) as exc:
            raise ManagementError(
                "delegation_unavailable", "Cannot verify service delegation; no fallback"
            ) from exc
        if response.get("ok") is not True:
            error = response.get("error", {})
            if not isinstance(error, dict) or not all(
                isinstance(error.get(key), str) for key in ("code", "message")
            ):
                raise ManagementError("invalid_response", "Invalid delegation error")
            raise ManagementError(
                error.get("code", "delegation_error"), error.get("message", "Delegation failed")
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise ManagementError("invalid_response", "Invalid delegation result")
        return result

    def perform(self, action: str, name: str | None, target: str | None) -> Any:
        result = self.request(action, name, target)
        if action == "list":
            return result["services"]
        if action != "start":
            return result
        record, payload = result["record"], result["payload"]
        # Only this worker-side call executes supervisor/repo code.
        services.launch(record, payload)
        observed = self.request("inspect", name, target, launch=record["delegated"]["launch"])
        return services.require_running(observed)
