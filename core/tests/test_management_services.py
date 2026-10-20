from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from http.client import HTTPConnection
from pathlib import Path
from typing import Any

import pytest

from lodex_core.management import services, worktrees
from lodex_core.management.common import ManagementError, read_json, write_private
from lodex_core.management.environment import LogRedactor
from lodex_core.management.processes import exited_without_reaping
from lodex_core.management.project_config import CONFIG, load
from lodex_core.management.store import Registry

from .support.management import register
from .support.services import service_config


def test_conflict_exit_and_lock(registry: Registry, repo: Path) -> None:
    service_config(repo)
    task = register(registry, repo)
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", task["ports"]["PORT"]))
        with pytest.raises(ManagementError, match="occupied"):
            services.start(registry, task, "http")
    with pytest.raises(ManagementError, match="failed"):
        services.start(registry, task, "bad")
    assert services.list_services(registry, task["id"])[0]["state"] == "failed"
    with registry.lock(task["id"]), pytest.raises(ManagementError, match="Another operation"):
        services.start(registry, task, "http")


@pytest.mark.parametrize("external", ["true", "false"])
def test_external_config_is_rejected_without_rewriting(repo: Path, external: str) -> None:
    recipe = (
        f'schema_version=1\n[services.api]\nexternal={external}\nurl="https://example.invalid"\n'
        + ('argv=["python3", "server.py"]\n' if external == "false" else "")
    )
    (repo / CONFIG).write_text(recipe)
    with pytest.raises(ManagementError, match=r"services.api.external.*no longer supported") as exc:
        load(repo / CONFIG)
    assert exc.value.code == "invalid_config"
    assert "env/secrets" in str(exc.value)
    assert (repo / CONFIG).read_text() == recipe


def test_legacy_external_records_are_read_only_and_survive_removal(
    registry: Registry, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_config(repo)
    register(registry, repo)
    task = worktrees.create(registry, "fixture", "HEAD", "legacy")
    record = {
        "id": f"{task['id']}-http",
        "taskenv": task["id"],
        "name": "http",
        "state": "external",
        "url": "https://example.invalid",
        "observed_at": "2026-10-01T00:00:00+00:00",
    }
    registry.put("service", record)

    def reject_control(directory: Path, action: str) -> dict[str, Any]:
        pytest.fail("Legacy records must never contact a process controller")

    monkeypatch.setattr(services, "control", reject_control)
    reader = Registry(registry.root, read_only=True)
    try:
        observed = services.list_services(reader, task["id"])[0]
        assert observed == {**record, "warning": services.LEGACY_EXTERNAL_MESSAGE}
    finally:
        reader.close()
    with pytest.raises(ManagementError, match="read-only") as exc:
        services.start(registry, task, "http")
    assert exc.value.code == "legacy_service"
    # A removed configuration must not prevent querying legacy records or cause control calls.
    (Path(task["path"]) / CONFIG).unlink()
    for action in (services.stop, services.logs):
        with pytest.raises(ManagementError, match="read-only") as exc:
            action(registry, task["id"], "http")
        assert exc.value.code == "legacy_service"
    assert worktrees.inspect(registry, task)["services"] == [observed]
    assert worktrees.remove(registry, task, yes=True, force=True)["removed"] is True
    worktrees.forget(registry, task, yes=True)
    assert registry.get("service", record["id"]) == record


def test_stale_handle_never_signals_pid(
    registry: Registry, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_config(repo)
    task = register(registry, repo)
    record = services.start(registry, task, "http")
    directory = Path(record["directory"])
    handle = read_json(directory / "control.json")

    def assert_running() -> None:
        assert services.refresh(record)["state"] == "running"
        connection = HTTPConnection("127.0.0.1", task["ports"]["PORT"], timeout=2)
        try:
            connection.request("GET", "/")
            assert connection.getresponse().status == 200
        finally:
            connection.close()

    def reject_signal(pid: int, signum: int) -> None:
        pytest.fail(f"Unauthenticated handle attempted signal {signum} to {pid}")

    try:
        assert_running()
        write_private(directory / "control.json", json.dumps({**handle, "token": "invalid"}))
        with monkeypatch.context() as patch:
            patch.setattr(os, "kill", reject_signal)
            patch.setattr(os, "killpg", reject_signal)
            with pytest.raises(ManagementError):
                services.stop(registry, task["id"], "http")
            assert services.refresh(record)["state"] == "unknown"
            with pytest.raises(ManagementError, match="unknown"):
                services.start(registry, task, "http")
        write_private(directory / "control.json", json.dumps(handle))
        assert_running()
    finally:
        write_private(directory / "control.json", json.dumps(handle))
        services.stop(registry, task["id"], "http")


def test_split_secret_log_redaction() -> None:
    redactor = LogRedactor(["sensitive", "long-secret"])
    output = b"".join(
        redactor.feed(piece) for piece in [b"a sen", b"siti", b"ve z long-", b"secret\n"]
    )
    output += redactor.feed(b"", final=True)
    assert output == b"a [REDACTED] z [REDACTED]\n"


def test_exit_observation_keeps_child_owned() -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read(); sys.exit(7)"],
        stdin=subprocess.PIPE,
    )
    try:
        assert not exited_without_reaping(child.pid)
        assert child.stdin is not None
        child.stdin.close()
        deadline = time.monotonic() + 5
        while not exited_without_reaping(child.pid):
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert exited_without_reaping(child.pid)
        assert child.wait(timeout=1) == 7
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_readiness_timeout_and_process_group(registry: Registry, repo: Path) -> None:
    (repo / CONFIG).write_text(
        "schema_version=1\n[ports]\nPORT=0\n[services.timeout]\n"
        f'argv=[{json.dumps(sys.executable)},"-c","import time; time.sleep(30)"]\n'
        'ready_port="PORT"\nready_timeout=0.2\n'
        "[services.group]\n"
        f'argv=[{json.dumps(sys.executable)},"-u","group.py"]\nscripts=["group.py"]\n'
    )
    (repo / "group.py").write_text(
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\n"
        "print(child.pid,flush=True)\ntime.sleep(30)\n"
    )
    task = register(registry, repo)
    with pytest.raises(ManagementError, match="failed"):
        services.start(registry, task, "timeout")
    failed = services.refresh(registry.get("service", f"{task['id']}-timeout"))
    assert failed["error"] == "readiness_timeout"
    record = services.start(registry, task, "group")
    pid = read_json(Path(record["directory"]) / "status.json")["pid"]
    try:
        assert services.stop(registry, task["id"], "group")["state"] == "stopped"
        with pytest.raises(ProcessLookupError):
            os.killpg(pid, 0)
    finally:
        try:
            services.stop(registry, task["id"], "group")
        except ManagementError:
            pass
