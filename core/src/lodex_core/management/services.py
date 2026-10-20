"""Service operations shared by CLI and future console callers."""

from __future__ import annotations

import json
import secrets
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from lodex_core.management.common import ManagementError, now, private_dir, read_json
from lodex_core.management.environment import (
    SecretProvider,
    command_argv,
    expand,
    inputs,
    log_tail,
    process_env,
)
from lodex_core.management.processes import STOP_GRACE_SECONDS
from lodex_core.management.project_config import check_command
from lodex_core.management.store import Registry

LEGACY_EXTERNAL_MESSAGE = (
    "Legacy external service record is read-only. Move connection settings to env/secrets; "
    "use a different service name for a managed process. No external process is controlled."
)


def control(directory: Path, action: str) -> dict[str, Any]:
    handle = read_json(directory / "control.json")
    try:
        with socket.create_connection(("127.0.0.1", handle["port"]), timeout=0.5) as connection:
            connection.sendall(json.dumps({"action": action, "token": handle["token"]}).encode())
            response: dict[str, Any] = json.loads(connection.recv(16384))
            return response
    except (OSError, ValueError) as exc:
        raise ManagementError(
            "unknown_service", "Service control handle cannot be verified"
        ) from exc


def refresh(record: dict[str, Any]) -> dict[str, Any]:
    record = dict(record)
    if record["state"] == "external":
        # Compatibility with saved URL-only records; never rewrite or control them.
        return {**record, "warning": LEGACY_EXTERNAL_MESSAGE}
    directory = Path(record["directory"])
    try:
        status = read_json(directory / "status.json")
        if status["state"] in ("starting", "running", "stopping"):
            status = control(directory, "inspect")
        record.update(status)
    except ManagementError:
        record.update(state="unknown", observed_at=now())
    return record


def list_services(registry: Registry, task_id: str) -> list[dict[str, Any]]:
    return [refresh(s) for s in registry.all("service") if s["taskenv"] == task_id]


def start(
    registry: Registry, task: dict[str, Any], service: str, provider: SecretProvider | None = None
) -> dict[str, Any]:
    with registry.lock(task["id"]):
        registry.reload_task(task)
        key = f"{task['id']}-{service}"
        previous = next((s for s in registry.all("service") if s["id"] == key), None)
        if previous and previous["state"] == "external":
            raise ManagementError("legacy_service", LEGACY_EXTERNAL_MESSAGE)
        config, values, known = inputs(registry, task, provider)
        spec = config["services"].get(service)
        if spec is None:
            raise ManagementError("unknown_service", f"No configured service: {service}")
        if previous and refresh(previous)["state"] not in (
            "stopped",
            "exited",
            "failed",
        ):
            raise ManagementError(
                "service_active",
                "Service is running, starting, stopping or unknown; inspect/stop first",
            )
        url = expand(spec["url"], values) if "url" in spec else None
        if url and any(secret in url for secret in known):
            raise ManagementError("secret_in_url", "Public service URL cannot contain secrets")
        record: dict[str, Any] = {
            "id": key,
            "taskenv": task["id"],
            "name": service,
            "url": url,
            "state": "starting",
            "observed_at": now(),
        }
        check_command(Path(task["path"]), spec, config)
        argv = command_argv(spec, values, known)
        ready_port = int(values[spec["ready_port"]]) if "ready_port" in spec else None
        if ready_port is not None:
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", ready_port))
                except OSError as exc:
                    raise ManagementError(
                        "port_conflict", f"Port {ready_port} is occupied"
                    ) from exc
        directory = registry.root / "runs" / uuid.uuid4().hex
        private_dir(directory)
        record["directory"] = str(directory)
        registry.put("service", record)
        payload = {
            "directory": str(directory),
            "token": secrets.token_hex(32),
            "argv": argv,
            "cwd": task["path"],
            "env": process_env(values),
            "secrets": known,
            "ready_port": ready_port,
            "ready_timeout": spec.get("ready_timeout", 10),
        }
        # Bootstrap using the installed package path, independent of target cwd/PYTHONPATH.
        bootstrap = (
            "import sys; sys.path.insert(0,sys.argv[1]); "
            "from lodex_core.management.runner import main; main()"
        )
        try:
            supervisor = subprocess.Popen(
                [sys.executable, "-c", bootstrap, str(Path(__file__).resolve().parents[2])],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            assert supervisor.stdin is not None
            supervisor.stdin.write(json.dumps(payload).encode())
            supervisor.stdin.close()
            deadline = time.monotonic() + payload["ready_timeout"] + STOP_GRACE_SECONDS + 2
            while time.monotonic() < deadline:
                if (directory / "status.json").exists():
                    record.update(read_json(directory / "status.json"))
                    if record["state"] not in ("starting", "stopping"):
                        registry.put("service", record)
                        if record["state"] != "running":
                            raise ManagementError(
                                "start_failed", f"Service failed; inspect {key} and logs"
                            )
                        return record
                if supervisor.poll() is not None:
                    break
                time.sleep(0.05)
        except (KeyboardInterrupt, OSError) as exc:
            record.update(state="unknown", observed_at=now())
            registry.put("service", record)
            raise ManagementError(
                "start_interrupted", "Inspect service before retrying start"
            ) from exc
        record.update(state="unknown", observed_at=now())
        registry.put("service", record)
        raise ManagementError(
            "start_unknown", "Startup handshake incomplete; inspect before retrying"
        )


def stop(registry: Registry, task_id: str, service: str) -> dict[str, Any]:
    with registry.lock(task_id):
        record = refresh(registry.get("service", f"{task_id}-{service}"))
        if record["state"] == "external":
            raise ManagementError("legacy_service", LEGACY_EXTERNAL_MESSAGE)
        if record["state"] in ("stopped", "exited", "failed"):
            return record
        control(Path(record["directory"]), "stop")
        deadline = time.monotonic() + STOP_GRACE_SECONDS + 2
        while time.monotonic() < deadline:
            status = read_json(Path(record["directory"]) / "status.json")
            if status["state"] in ("stopped", "exited", "failed"):
                record.update(status)
                registry.put("service", record)
                return record
            time.sleep(0.05)
        raise ManagementError("stop_unknown", "Stop requested; inspect to determine final state")


def logs(registry: Registry, task_id: str, service: str) -> dict[str, Any]:
    record = registry.get("service", f"{task_id}-{service}")
    if record["state"] == "external":
        raise ManagementError("legacy_service", LEGACY_EXTERNAL_MESSAGE)
    return {
        "id": record["id"],
        "tail": log_tail(Path(record["directory"]) / "output.log"),
        "limit_bytes": 65536,
    }
