from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from lodex_cli import main as cli
from lodex_core.management import operations, worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.project_config import CONFIG
from lodex_core.management.store import Registry

from .support.management import register
from .support.operations import recipe


@pytest.mark.parametrize(
    "signal_number,expected",
    [(signal.SIGINT, "interrupted"), (signal.SIGTERM, "interrupted"), (signal.SIGKILL, "unknown")],
)
def test_command_interrupt_and_forced_death(
    registry: Registry, repo: Path, signal_number: int, expected: str
) -> None:
    (repo / CONFIG).write_text(
        "schema_version=1\n[commands.prepare]\n"
        f'argv=[{json.dumps(sys.executable)},"-u","-c",'
        '"import os,time; print(os.getpid(),flush=True); time.sleep(30)"]\n'
    )
    task = register(registry, repo)
    caller = subprocess.Popen(
        [sys.executable, "-m", "lodex_cli.main", "prepare", "--target", task["id"], "--json"],
        env={**os.environ, "LODEX_HOME": str(registry.root)},
        stdout=subprocess.PIPE,
    )
    child_pid: int | None = None
    try:
        deadline = time.monotonic() + 5
        record: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            records = registry.all("operation")
            if records:
                record = records[0]
                log = operations.logs(record)["tail"].strip()
                if log:
                    child_pid = int(log)
                    break
            time.sleep(0.02)
        assert child_pid is not None and record is not None
        caller.send_signal(signal_number)
        caller.communicate(timeout=5)
        current = operations.inspect_operation(registry, registry.get("operation", record["id"]))
        assert current["state"] == expected
        assert worktrees.inspect(registry, task)["operations"][0]["state"] == expected
        assert len(registry.all("operation")) == 1
    finally:
        if caller.poll() is None:
            caller.kill()
            caller.wait()
        if child_pid is not None:
            try:
                os.killpg(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("signal_number", [signal.SIGINT, signal.SIGTERM])
@pytest.mark.parametrize("ignore_term", [False, True])
def test_command_interrupt_waits_for_descendants(
    registry: Registry, repo: Path, signal_number: int, ignore_term: bool
) -> None:
    (repo / CONFIG).write_text(
        "schema_version=1\n[commands.prepare]\nargv="
        + json.dumps([sys.executable, "-u", "parent.py"])
        + "\n"
    )
    (repo / "parent.py").write_text(
        "import os,subprocess,sys,time\nfrom pathlib import Path\n"
        "Path('parent-pid').write_text(str(os.getpid()))\n"
        "subprocess.Popen([sys.executable,'-u','child.py'])\n"
        "time.sleep(60)\n"
    )
    (repo / "child.py").write_text(
        "import json,os,signal,sys,time\nfrom pathlib import Path\n"
        "def stop(*args):\n"
        "    Path('term-seen').touch()\n"
        "    print('child received TERM',flush=True)\n"
        + (
            ""
            if ignore_term
            else "    time.sleep(.4)\n"
            "    Path('child-stopped').touch()\n"
            "    Path(os.environ['LODEX_RESULT_FILE']).write_text(json.dumps({'urls':"
            "['http://127.0.0.1/interrupted']}))\n"
            "    print('child stopped gracefully',flush=True)\n"
            "    sys.exit(0)\n"
        )
        + "signal.signal(signal.SIGTERM,stop)\n"
        "Path('child-ready').touch()\n"
        "time.sleep(60)\n"
    )
    task = register(registry, repo)
    caller = subprocess.Popen(
        [sys.executable, "-m", "lodex_cli.main", "prepare", "--target", task["id"], "--json"],
        env={**os.environ, "LODEX_HOME": str(registry.root)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    group: int | None = None
    try:
        deadline = time.monotonic() + 5
        while not (repo / "child-ready").exists():
            assert time.monotonic() < deadline, "Repo child did not start"
            time.sleep(0.02)
        group = int((repo / "parent-pid").read_text())
        caller.send_signal(signal_number)
        deadline = time.monotonic() + 2
        while not (repo / "term-seen").exists():
            assert time.monotonic() < deadline, "Repo child did not receive TERM"
            time.sleep(0.02)
        record = registry.all("operation")[0]
        assert operations.inspect_operation(registry, record)["state"] == "running"
        assert registry.busy(task["id"]) and registry.busy(f"op-{record['id']}")
        # Another interrupt must not abort the group's cleanup or release its locks.
        caller.send_signal(signal_number)
        output, errors = caller.communicate(timeout=6)
        assert caller.returncode == 1, errors
        result = json.loads(output)["result"]
        assert result["state"] == "interrupted" and result["exit_code"] == -signal.SIGTERM
        assert (repo / "child-stopped").exists() is not ignore_term
        assert "child received TERM" in operations.logs(result)["tail"]
        if not ignore_term:
            assert "child stopped gracefully" in operations.logs(result)["tail"]
            assert result["result"]["urls"] == ["http://127.0.0.1/interrupted"]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            pytest.fail("Repo process group survived interruption")
        assert not registry.busy(task["id"]) and not registry.busy(f"op-{record['id']}")
    finally:
        if caller.poll() is None:
            caller.kill()
            caller.wait()
        if group is not None:
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                pass  # Darwin may retain only zombies briefly after the test.


def test_missing_cleanup_and_forget_preserves_evidence(
    registry: Registry,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    recipe(repo, secret=False)
    task = register(registry, repo)
    record = operations.run(registry, task, "prepare")
    (repo / CONFIG).write_text("schema_version=1\n")
    with pytest.raises(ManagementError, match="handle manually"):
        operations.run(registry, task, "cleanup")
    repo.rename(repo.with_name("missing"))
    with pytest.raises(ManagementError, match="missing"):
        operations.run(registry, task, "cleanup")
    missing = worktrees.inspect(registry, task)
    assert not missing["cleanup"]["available"]
    assert missing["known_resources"][0]["state"] == "present"
    monkeypatch.setenv("LODEX_HOME", str(registry.root))
    assert cli.main(["worktree", "forget", "--target", task["id"], "--json"]) == 0
    assert "does not stop services" in capsys.readouterr().out
    assert cli.main(["worktree", "forget", "--target", task["id"], "--yes", "--json"]) == 0
    assert registry.get("operation", record["id"])["state"] == "succeeded"


def test_cli_full_two_env_flow(repo: Path, tmp_path: Path) -> None:
    recipe(repo, secret=False)
    with (repo / CONFIG).open("a") as stream:
        stream.write(
            "[ports]\nPORT=0\n[services.http]\n"
            f'argv=[{json.dumps(sys.executable)},"-u","-m","http.server","${{PORT}}","--bind","127.0.0.1"]\n'
            'ready_port="PORT"\nurl="http://127.0.0.1:${PORT}"\n'
        )
    env = {**os.environ, "LODEX_HOME": str(tmp_path / "cli-state")}

    def call(*args: str, expected: int = 0) -> Any:
        result = subprocess.run(
            [sys.executable, "-m", "lodex_cli.main", *args, "--json"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == expected, result.stdout + result.stderr
        return json.loads(result.stdout).get("result")

    call("project", "add", "fixture", str(repo))
    tasks = [
        call("worktree", "create", "fixture", "--ref", "HEAD", "--branch", branch)
        for branch in ("a", "b")
    ]
    try:
        for task in tasks:
            target = task["id"]
            assert call("context", "--target", task["path"])["id"] == target
            assert call("prepare", "--target", target)["state"] == "succeeded"
            assert call("run", "verify", "--target", target, expected=1)["state"] == "failed"
            assert call("service", "start", "http", "--target", target)["state"] == "running"
            call("service", "logs", "http", "--target", target)
        for task in tasks:
            target = task["id"]
            call("service", "stop", "http", "--target", target)
            assert call("cleanup", "--target", target)["state"] == "succeeded"
            assert call("worktree", "remove", "--target", target)["operations"]
            assert call("worktree", "remove", "--target", target, "--yes", "--force")["removed"]
            assert call("worktree", "inspect", "--target", target)["state"] == "missing"
    finally:
        for task in tasks:
            call("service", "stop", "http", "--target", task["id"])
