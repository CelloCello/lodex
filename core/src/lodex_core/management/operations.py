"""Foreground repo commands and durable known/unknown outcomes. Never retries."""

from __future__ import annotations

import json
import os
import selectors
import signal
import stat
import subprocess
import time
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from lodex_core.management import settings
from lodex_core.management.common import ManagementError, now, private_dir
from lodex_core.management.environment import (
    LogRedactor,
    SecretProvider,
    command_argv,
    inputs,
    log_tail,
    process_env,
    redact,
)
from lodex_core.management.processes import (
    STOP_GRACE_SECONDS,
    exited_without_reaping,
    signal_group,
)
from lodex_core.management.project_config import CONFIG, check_command, digest, load, supply
from lodex_core.management.service_runtime import runtime_root
from lodex_core.management.store import Registry
from lodex_core.management.workspace import validate_checkout
from lodex_core.management.worktrees import git, require_prepared, require_present


def inspect_operation(registry: Registry, record: dict[str, Any]) -> dict[str, Any]:
    if record["state"] == "running" and not registry.busy(f"op-{record['id']}"):
        record = registry.get("operation", record["id"])
        if record["state"] == "running":
            record.update(state="unknown", observed_at=now())
    return record


def result_data(path: Path, known: list[str], *, dir_fd: int | None = None) -> dict[str, Any]:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except FileNotFoundError:
        return {"resources": [], "urls": []}
    except OSError as exc:
        raise ManagementError(
            "invalid_result", "Repo result must be a private regular file"
        ) from exc
    with os.fdopen(descriptor, "rb") as stream:
        observed = os.fstat(stream.fileno())
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            raise ManagementError("invalid_result", "Repo result must be a private regular file")
        if observed.st_size > 1024 * 1024:
            raise ManagementError("invalid_result", "Repo result exceeds 1 MiB")
        try:
            raw = json.loads(stream.read(1024 * 1024 + 1))
        except (ValueError, RecursionError) as exc:
            raise ManagementError("invalid_result", "Cannot read valid repo result") from exc
    if not isinstance(raw, dict):
        raise ManagementError("invalid_result", "Repo result must be an object")
    if set(raw) - {"resources", "urls"}:
        raise ManagementError("invalid_result", "Repo result accepts only resources and urls")
    resources = raw.setdefault("resources", [])
    urls = raw.setdefault("urls", [])
    if not isinstance(resources, list) or not isinstance(urls, list):
        raise ManagementError("invalid_result", "resources and urls must be arrays")
    for resource in resources:
        if not isinstance(resource, dict) or set(resource) - {
            "name",
            "kind",
            "id",
            "scope",
            "state",
        }:
            raise ManagementError("invalid_result", "Invalid resource fields")
        if not all(
            isinstance(resource.get(k), str) and resource[k] for k in ("name", "kind", "id")
        ):
            raise ManagementError("invalid_result", "Resources need name, kind and id strings")
        if resource.get("scope") not in ("exclusive", "shared"):
            raise ManagementError("invalid_result", "Resources need exclusive/shared scope")
        if resource.get("state") not in ("present", "removed", "unknown"):
            raise ManagementError(
                "invalid_result", "Resource state must be present/removed/unknown"
            )
    if any(not isinstance(url, str) or not url.startswith(("http://", "https://")) for url in urls):
        raise ManagementError("invalid_result", "urls must contain HTTP(S) URLs")

    def sanitized(value: Any) -> Any:
        if isinstance(value, str):
            return redact(value, known)
        if isinstance(value, list):
            return [sanitized(item) for item in value]
        if isinstance(value, dict):
            return {key: sanitized(item) for key, item in value.items()}
        return value

    result: dict[str, Any] = sanitized(raw)
    return result


def run(
    registry: Registry,
    task: dict[str, Any],
    command: str,
    provider: SecretProvider | None = None,
    source: Path | None = None,
    *,
    execution: Callable[[Path], list[str]] | None = None,
    execution_env: dict[str, str] | None = None,
    approved_secret_refs: dict[str, str] | None = None,
    result_runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with registry.lock(task["id"]), ExitStack() as held:
        registry.reload_task(task)
        root = require_present(task)
        if execution is not None:
            # Registration takes this task lock too. Recheck the saved sandbox's
            # write scope after acquiring it, before executing any cleanup code.
            validate_checkout(registry, task, worker=True)
        if command != "prepare":
            require_prepared(task)
        if command == "prepare":
            project = registry.get("project", task["project"])
            provenance = supply(root, source or Path(project["source"]))
            if provenance["method"] == "copied":
                task["config_source"] = provenance
        configuration = load(root / CONFIG)
        if approved_secret_refs is not None and configuration["secrets"] != approved_secret_refs:
            raise ManagementError(
                "execution_scope", "Secret references changed; review a new worker policy"
            )
        config, values, known = inputs(registry, task, provider, configuration=configuration)
        spec = config["commands"].get(command)
        if spec is None:
            raise ManagementError(
                "missing_command",
                f"No {command} command; restore configuration/script or handle manually",
            )
        check_command(root, spec, config)
        argv = command_argv(spec, values, known)
        delivery = config["taskenv"].get("env_file") if command == "prepare" else None
        if delivery is not None:
            settings.export_resolved(registry, task, delivery, values, known)
        checkout_commit = git(root, "rev-parse", "HEAD") if command == "prepare" else None
        operation_id = uuid.uuid4().hex
        held.enter_context(registry.lock(f"op-{operation_id}"))
        directory = registry.root / "operations" / operation_id
        private_dir(directory)
        result_path = directory / "result.json"
        result_fd = None
        if result_runtime is not None:
            # Keep an open, identity-checked directory handle. Repo code can
            # write its result, but cannot redirect manager reads or unlinking.
            result_fd = held.enter_context(runtime_root(result_runtime))
            result_path = Path(result_runtime["root"]) / f"result-{operation_id}.json"
        values["LODEX_RESULT_FILE"] = str(result_path)
        record: dict[str, Any] = {
            "id": operation_id,
            "taskenv": task["id"],
            "command": command,
            "state": "running",
            "exit_code": None,
            "directory": str(directory),
            "started_at": now(),
            "observed_at": now(),
        }
        registry.put("operation", record)
        redactor = LogRedactor(known)
        child: subprocess.Popen[bytes] | None = None
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        requested_stop = False
        stop_deadline: float | None = None

        def interrupted(signum: int, frame: object) -> None:
            nonlocal requested_stop
            requested_stop = True

        fd = os.open(directory / "output.log", os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb", buffering=0) as log:
            try:
                for sig in previous:
                    signal.signal(sig, interrupted)
                environment = {
                    **process_env(values, caller_network=execution is None),
                    **(execution_env or {}),
                }
                # Repo inputs reach the command only after the wrapper establishes
                # its sandbox. Loader variables must not affect that outer process.
                launcher_environment = (
                    {**process_env({}), **(execution_env or {})}
                    if execution is not None
                    else environment
                )
                child = subprocess.Popen(
                    execution(result_path) if execution is not None else argv,
                    cwd=root,
                    env=launcher_environment,
                    stdin=subprocess.PIPE if execution is not None else subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                if execution is not None:
                    assert child.stdin is not None
                    try:
                        # Private pipe, never secret-bearing argv or staging files.
                        child.stdin.write(
                            json.dumps({"argv": argv, "environment": environment}).encode()
                        )
                    finally:
                        child.stdin.close()
                assert child.stdout is not None
                os.set_blocking(child.stdout.fileno(), False)
                with selectors.DefaultSelector() as selector:
                    selector.register(child.stdout, selectors.EVENT_READ)
                    while True:
                        for _, _events in selector.select(0.1):
                            data = os.read(child.stdout.fileno(), 8192)
                            if data:
                                log.write(redactor.feed(data))
                            else:
                                selector.unregister(child.stdout)
                        if requested_stop and stop_deadline is None:
                            signal_group(child, signal.SIGTERM)
                            stop_deadline = time.monotonic() + STOP_GRACE_SECONDS
                        if stop_deadline is not None:
                            if time.monotonic() < stop_deadline:
                                continue
                            # Keep the leader unreaped through the final group signal,
                            # even if it exited before descendants finished stopping.
                            signal_group(child, signal.SIGKILL)
                        elif not exited_without_reaping(child.pid):
                            continue
                        record["exit_code"] = child.wait()
                        while True:
                            try:
                                data = os.read(child.stdout.fileno(), 8192)
                            except BlockingIOError:
                                break
                            if not data:
                                break
                            log.write(redactor.feed(data))
                        break
                record["state"] = "succeeded" if child.returncode == 0 else "failed"
                if stop_deadline is not None:
                    record["state"] = "interrupted"
                try:
                    record["result"] = result_data(
                        Path(result_path.name) if result_fd is not None else result_path,
                        known,
                        dir_fd=result_fd,
                    )
                except ManagementError as exc:
                    if stop_deadline is not None:
                        record["error"] = "invalid_partial_result"
                    else:
                        record.update(state="unknown", error=exc.code)
            except OSError:
                record.update(state="failed", error="command_launch_failed")
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
                if child is not None and child.stdout is not None:
                    child.stdout.close()
                log.write(redactor.feed(b"", final=True))
                try:
                    os.unlink(
                        result_path.name if result_fd is not None else result_path, dir_fd=result_fd
                    )
                except FileNotFoundError:
                    pass
                record["observed_at"] = now()
                if command == "prepare" and record["state"] == "succeeded":
                    task.pop("prepare_required", None)
                    registry.put("taskenv", task)
                    record["handoff"] = {
                        "version": 1,
                        "taskenv": task["id"],
                        "path": str(root),
                        "project": task["project"],
                        "binding_revision": task.get("binding_revision", 0),
                        "base_commit": task.get("base_commit"),
                        "checkout_commit": checkout_commit,
                        "configuration": str(root / CONFIG),
                        "configuration_digest": digest(config),
                        "env_file": str(root / delivery) if delivery is not None else None,
                        "configured_services": sorted(config["services"]),
                        "secret_refs": config["secrets"],
                        "prepare_operation": operation_id,
                    }
                registry.put("operation", record)
        return record


def logs(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["id"],
        "tail": log_tail(Path(record["directory"]) / "output.log"),
        "limit_bytes": 65536,
    }
