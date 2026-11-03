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

from lodex_core.management import service_runtime
from lodex_core.management.common import ManagementError, now, private_dir, read_json, write_private
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
TERMINAL_KIND = "service-terminal"
ACK_WARNING = "Supervisor acknowledgement is unconfirmed; manager can use service retry-acks"


def control(directory: Path, action: str) -> dict[str, Any]:
    handle = read_json(directory / "control.json")
    return send_control(handle, action)


def send_control(handle: dict[str, Any], action: str) -> dict[str, Any]:
    try:
        if "socket" in handle:
            connection = socket.socket(socket.AF_UNIX)
            connection.settimeout(0.5)
            try:
                connection.connect(handle["socket"])
            except BaseException:
                connection.close()
                raise
        else:
            connection = socket.create_connection(("127.0.0.1", handle["port"]), timeout=0.5)
        with connection:
            connection.sendall(json.dumps({"action": action, "token": handle["token"]}).encode())
            response: dict[str, Any] = json.loads(connection.recv(16384))
            return response
    except (OSError, ValueError, RecursionError) as exc:
        raise ManagementError(
            "unknown_service", "Service control handle cannot be verified"
        ) from exc


def record_control(record: dict[str, Any], action: str) -> dict[str, Any]:
    if "delegated" in record:
        with service_runtime.runtime_root(record["delegated"]):
            handle = read_json(Path(record["delegated"]["control_file"]))
            return service_runtime.parse_status(send_control(handle, action))
    return control(Path(record["directory"]), action)


def refresh(record: dict[str, Any]) -> dict[str, Any]:
    record = dict(record)
    if record["state"] == "external":
        # Compatibility with saved URL-only records; never rewrite or control them.
        return {**record, "warning": LEGACY_EXTERNAL_MESSAGE}
    try:
        if "delegated" in record:
            # Only a receipt saved by the manager can outlive the supervisor.
            # Worker-writable files never authorize stopping, replacement or removal.
            if "terminal" in record:
                status = service_runtime.parse_status(record["terminal"])
            else:
                status = record_control(record, "inspect")
                if status["state"] in service_runtime.TERMINAL_STATES:
                    record["terminal"] = dict(status)
        else:
            status = service_runtime.status(record)
            if status["state"] in ("starting", "running", "stopping"):
                status = record_control(record, "inspect")
        record.update(status)
    except (ManagementError, OSError, ValueError):
        record.update(state="unknown", observed_at=now())
    return record


def record_observation(registry: Registry, record: dict[str, Any]) -> dict[str, Any]:
    """Persist under the task lock before releasing a terminal delegated supervisor."""
    registry.put("service", record)
    if "delegated" in record and "terminal" in record:
        launch_id = record["delegated"]["launch"]
        try:
            receipt = registry.get(TERMINAL_KIND, launch_id)
        except ManagementError as exc:
            if exc.code != "not_found":
                raise
            receipt = {**record, "id": launch_id, "service_id": record["id"]}
            # Commit the independent receipt before ACK or replacement of the service row.
            registry.put(TERMINAL_KIND, receipt)
        record["terminal_acknowledged"] = acknowledge_receipt(registry, receipt)
        registry.put("service", record)
    return with_pending_acks(registry, record)


def acknowledge_receipt(registry: Registry, receipt: dict[str, Any]) -> bool:
    """Retry only a manager-owned terminal receipt; caller holds the task lock."""
    if receipt.get("terminal_acknowledged"):
        return True
    try:
        record_control(receipt, "ack_terminal")
    except (ManagementError, OSError):
        return False
    registry.put(TERMINAL_KIND, {**receipt, "terminal_acknowledged": True})
    return True


def pending_acks(registry: Registry, task_id: str, service: str) -> list[dict[str, Any]]:
    return [
        receipt
        for receipt in registry.all(TERMINAL_KIND)
        if receipt["taskenv"] == task_id
        and receipt["name"] == service
        and not receipt.get("terminal_acknowledged")
    ]


def with_pending_acks(registry: Registry, record: dict[str, Any]) -> dict[str, Any]:
    record = dict(record)
    record.pop("pending_acks", None)
    if record.get("warning") == ACK_WARNING:
        record.pop("warning")
    pending = pending_acks(registry, record["taskenv"], record["name"])
    if not pending:
        return record
    return {
        **record,
        "pending_acks": [receipt["id"] for receipt in pending],
        "warning": ACK_WARNING,
    }


def retry_acks(registry: Registry, task_id: str, service: str) -> dict[str, Any]:
    """Acknowledge retained terminal launches without controlling the current service."""
    with registry.lock(task_id):
        acknowledged = []
        for receipt in pending_acks(registry, task_id, service):
            if not acknowledge_receipt(registry, receipt):
                continue
            acknowledged.append(receipt["id"])
            try:
                current = registry.get("service", receipt["service_id"])
            except ManagementError as exc:
                if exc.code == "not_found":
                    continue
                raise
            if current.get("delegated", {}).get("launch") == receipt["id"]:
                registry.put("service", {**current, "terminal_acknowledged": True})
        result = with_pending_acks(registry, {"taskenv": task_id, "name": service})
        return {
            **result,
            "acknowledged": acknowledged,
            "pending_acks": result.get("pending_acks", []),
        }


def list_services(registry: Registry, task_id: str) -> list[dict[str, Any]]:
    return [
        with_pending_acks(registry, refresh(s))
        for s in registry.all("service")
        if s["taskenv"] == task_id
    ]


def prepare_start(
    registry: Registry,
    task: dict[str, Any],
    service: str,
    provider: SecretProvider | None = None,
    *,
    runtime: dict[str, Any] | None = None,
    configuration: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reserve a launch under the caller's task lock; never execute repo code."""
    registry.reload_task(task)
    key = f"{task['id']}-{service}"
    previous = next((s for s in registry.all("service") if s["id"] == key), None)
    if previous and previous["state"] == "external":
        raise ManagementError("legacy_service", LEGACY_EXTERNAL_MESSAGE)
    config, values, known = inputs(registry, task, provider, configuration=configuration)
    spec = config["services"].get(service)
    if spec is None:
        raise ManagementError("unknown_service", f"No configured service: {service}")
    if previous:
        observed = refresh(previous)
        if observed["state"] not in service_runtime.TERMINAL_STATES:
            raise ManagementError(
                "service_active",
                "Service is running, starting, stopping or unknown; inspect/stop first",
            )
        if "delegated" in observed:
            record_observation(registry, observed)
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
        "stop_timeout": spec.get("stop_timeout", STOP_GRACE_SECONDS),
    }
    check_command(Path(task["path"]), spec, config)
    argv = command_argv(spec, values, known)
    ready_argv = (
        command_argv({"argv": spec["ready_argv"]}, values, known) if "ready_argv" in spec else None
    )
    ready_port = int(values[spec["ready_port"]]) if "ready_port" in spec else None
    if ready_port is not None:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", ready_port))
            except OSError as exc:
                raise ManagementError("port_conflict", f"Port {ready_port} is occupied") from exc
    launch_id = uuid.uuid4().hex
    directory = (Path(runtime["root"]) if runtime else registry.root) / "runs" / launch_id
    if not runtime:
        private_dir(directory)
    record["directory"] = str(directory)
    if runtime:
        record["delegated"] = {
            **runtime,
            "launch": launch_id,
            "control_file": str(registry.root / "runs" / launch_id / "control.json"),
        }
    registry.put("service", record)
    payload = {
        "directory": str(directory),
        "token": secrets.token_hex(32),
        "argv": argv,
        "cwd": task["path"],
        "env": process_env(values),
        "secrets": known,
        "ready_port": ready_port,
        "ready_argv": ready_argv,
        "ready_timeout": spec.get("ready_timeout", 10),
        "stop_timeout": record["stop_timeout"],
    }
    if runtime:
        payload["control_socket"] = str(Path(runtime["root"]) / f"{launch_id[:12]}.sock")
        write_private(
            Path(record["delegated"]["control_file"]),
            json.dumps({"socket": payload["control_socket"], "token": payload["token"]}),
        )
    return record, payload


def launch(record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Execute in the calling process's sandbox, without opening the registry."""
    private_dir(Path(record["directory"]))
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
        deadline = time.monotonic() + payload["ready_timeout"] + record["stop_timeout"] + 3
        while time.monotonic() < deadline:
            if (Path(record["directory"]) / "status.json").exists():
                status = service_runtime.status(record)
                if status["state"] not in ("starting", "stopping"):
                    return status
            if supervisor.poll() is not None:
                break
            time.sleep(0.05)
    except (KeyboardInterrupt, OSError) as exc:
        raise ManagementError("start_interrupted", "Inspect service before retrying start") from exc
    return {"state": "unknown", "observed_at": now()}


def require_running(record: dict[str, Any]) -> dict[str, Any]:
    if record["state"] == "running":
        return record
    if record["state"] in ("stopped", "failed", "exited"):
        raise ManagementError("start_failed", f"Service failed; inspect {record['id']} and logs")
    raise ManagementError("start_unknown", "Startup handshake incomplete; inspect before retrying")


def start(
    registry: Registry, task: dict[str, Any], service: str, provider: SecretProvider | None = None
) -> dict[str, Any]:
    with registry.lock(task["id"]):
        record, payload = prepare_start(registry, task, service, provider)
        try:
            record.update(launch(record, payload))
        except ManagementError:
            record.update(state="unknown", observed_at=now())
            registry.put("service", record)
            raise
        registry.put("service", record)
        return with_pending_acks(registry, require_running(record))


def stop(registry: Registry, task_id: str, service: str) -> dict[str, Any]:
    with registry.lock(task_id):
        return stop_locked(registry, task_id, service)


def stop_locked(registry: Registry, task_id: str, service: str) -> dict[str, Any]:
    """Stop a saved service while the caller holds its task lock."""
    record = refresh(registry.get("service", f"{task_id}-{service}"))
    if record["state"] == "external":
        raise ManagementError("legacy_service", LEGACY_EXTERNAL_MESSAGE)
    if record["state"] in service_runtime.TERMINAL_STATES:
        return (
            record_observation(registry, record)
            if "delegated" in record
            else with_pending_acks(registry, record)
        )
    record_control(record, "stop")
    deadline = time.monotonic() + record.get("stop_timeout", STOP_GRACE_SECONDS) + 3
    while time.monotonic() < deadline:
        record = (
            refresh(record)
            if "delegated" in record
            else {**record, **service_runtime.status(record)}
        )
        if record["state"] in service_runtime.TERMINAL_STATES:
            return record_observation(registry, record)
        time.sleep(0.05)
    registry.put("service", {**record, "state": "unknown", "observed_at": now()})
    raise ManagementError("stop_unknown", "Stop requested; inspect to determine final state")


def logs(registry: Registry, task_id: str, service: str) -> dict[str, Any]:
    record = registry.get("service", f"{task_id}-{service}")
    if record["state"] == "external":
        raise ManagementError("legacy_service", LEGACY_EXTERNAL_MESSAGE)
    observed = with_pending_acks(registry, record)
    return {
        "id": record["id"],
        "tail": (
            service_runtime.owned_bytes(record, "output.log", tail=True).decode(
                "utf-8", errors="replace"
            )
            if "delegated" in record
            else log_tail(Path(record["directory"]) / "output.log")
        ),
        "limit_bytes": 65536,
        **{key: observed[key] for key in ("pending_acks", "warning") if key in observed},
    }
