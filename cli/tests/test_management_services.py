from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from http.client import HTTPConnection
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lodex_cli.main import app
from lodex_core.management import services, worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.environment import inputs
from lodex_core.management.project_config import CONFIG
from lodex_core.management.secrets import SQLiteSecrets
from lodex_core.management.store import Registry

from .support.management import register
from .support.services import service_config


def test_cli_legacy_external_records_remain_inspectable(
    registry: Registry, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = register(registry, repo)
    record = {
        "id": f"{task['id']}-old-api",
        "taskenv": task["id"],
        "name": "old-api",
        "state": "external",
        "url": "https://example.invalid",
    }
    registry.put("service", record)
    monkeypatch.setenv("LODEX_HOME", str(registry.root))
    runner = CliRunner()
    result = runner.invoke(app, ["service", "list", "--target", task["id"], "--json"])
    assert result.exit_code == 0, result.output
    observed = json.loads(result.stdout)["result"][0]
    assert observed["url"] == record["url"] and "read-only" in observed["warning"]
    for action in ("start", "stop", "logs"):
        result = runner.invoke(
            app, ["service", action, "old-api", "--target", task["id"], "--json"]
        )
        assert result.exit_code == 1, result.output
        assert json.loads(result.stdout)["error"]["code"] == "legacy_service"
    assert registry.get("service", record["id"]) == record


def test_two_services_survive_new_caller_and_config_changes(
    registry: Registry,
    repo: Path,
) -> None:
    service_config(repo)
    with (repo / CONFIG).open("a") as recipe:
        recipe.write(
            '\n[env]\nUPSTREAM_URL="https://shared.example.invalid"\n'
            '[secrets]\nUPSTREAM_TOKEN="secret:shared-upstream"\n'
        )
    SQLiteSecrets(registry).set("secret:shared-upstream", "fixture-shared-token")
    register(registry, repo)
    a = worktrees.create(registry, "fixture", "HEAD", "a")
    b = worktrees.create(registry, "fixture", "HEAD", "b")
    env = {**os.environ, "LODEX_HOME": str(registry.root)}
    assert a["ports"]["PORT"] != b["ports"]["PORT"]
    try:
        for task in (a, b):
            # Both taskenvs use the same upstream, but each owns its local mock process.
            _, values, _ = inputs(registry, task)
            assert values["UPSTREAM_URL"] == "https://shared.example.invalid"
            assert values["UPSTREAM_TOKEN"] == "fixture-shared-token"
            (Path(task["path"]) / "mock.txt").write_text(task["id"])
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lodex_cli.main",
                    "service",
                    "start",
                    "http",
                    "--target",
                    task["id"],
                    "--json",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            connection = HTTPConnection("127.0.0.1", task["ports"]["PORT"], timeout=2)
            try:
                connection.request("GET", "/mock.txt")
                response = connection.getresponse()
                assert response.status == 200 and response.read().decode() == task["id"]
            finally:
                connection.close()
        assert services.start(registry, a, "worker")["url"] is None
        # Secret redaction may buffer a short log suffix until the process exits.
        assert services.stop(registry, a["id"], "worker")["state"] == "stopped"
        assert services.logs(registry, a["id"], "worker")["tail"].strip() == "123"
        (Path(a["path"]) / CONFIG).write_text("schema_version=1\n")
        assert services.list_services(registry, a["id"])[0]["state"] == "running"
        assert services.stop(registry, a["id"], "http")["state"] == "stopped"
        assert services.refresh(registry.get("service", f"{b['id']}-http"))["state"] == "running"
        (Path(b["path"]) / CONFIG).unlink()
        Path(b["path"]).rename(Path(b["path"]).with_name("moved-b"))
        assert services.stop(registry, b["id"], "http")["state"] == "stopped"
        assert worktrees.inspect(registry, b)["state"] == "missing"
    finally:
        for task, service in ((a, "http"), (a, "worker"), (b, "http")):
            try:
                services.stop(registry, task["id"], service)
            except ManagementError:
                pass


def test_start_caller_interruption_preserves_handle(registry: Registry, repo: Path) -> None:
    import signal

    (repo / CONFIG).write_text(
        "schema_version=1\n[ports]\nPORT=0\n[services.slow]\n"
        f'argv=[{json.dumps(sys.executable)},"-u","-c","import time; time.sleep(60)"]\n'
        'ready_port="PORT"\nready_timeout=10\n'
    )
    task = register(registry, repo)
    caller = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "lodex_cli.main",
            "service",
            "start",
            "slow",
            "--target",
            task["id"],
            "--json",
        ],
        env={**os.environ, "LODEX_HOME": str(registry.root)},
        stdout=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 5
        record: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            records = registry.all("service")
            if records and (Path(records[0]["directory"]) / "status.json").exists():
                record = records[0]
                break
            time.sleep(0.02)
        assert record is not None
        caller.send_signal(signal.SIGINT)
        output, _ = caller.communicate(timeout=5)
        assert json.loads(output)["error"]["code"] == "start_interrupted"
        assert services.stop(registry, task["id"], "slow")["state"] == "stopped"
    finally:
        if caller.poll() is None:
            caller.kill()
            caller.wait()
        try:
            services.stop(registry, task["id"], "slow")
        except ManagementError:
            pass


@pytest.mark.parametrize("ignore_term", [False, True])
@pytest.mark.parametrize("leader_exits", [False, True])
def test_stop_waits_for_descendants_after_leader_exits(
    registry: Registry, repo: Path, ignore_term: bool, leader_exits: bool
) -> None:
    (repo / CONFIG).write_text(
        "schema_version=1\n[services.group]\n"
        f'argv=[{json.dumps(sys.executable)},"-u","parent.py"]\n'
        'scripts=["parent.py","child.py"]\n'
    )
    (repo / "parent.py").write_text(
        "import subprocess, sys, time\nfrom pathlib import Path\n"
        "subprocess.Popen([sys.executable, '-u', 'child.py'])\n"
        "while not Path('parent-exit').exists():\n    time.sleep(0.02)\n"
        "sys.exit(7)\n"
    )
    (repo / "child.py").write_text(
        "import os, signal, sys, time\nfrom pathlib import Path\n"
        "def stop(*args):\n"
        "    time.sleep(1)\n"
        "    Path('child-stopped').write_text('done')\n"
        "    sys.exit(0)\n"
        f"signal.signal(signal.SIGTERM, {'signal.SIG_IGN' if ignore_term else 'stop'})\n"
        "Path('child-ready').write_text(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    task = register(registry, repo)
    record = services.start(registry, task, "group")
    pid = record["pid"]
    try:
        deadline = time.monotonic() + 5
        while not (repo / "child-ready").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert (repo / "child-ready").exists()
        if leader_exits:
            (repo / "parent-exit").touch()
        else:
            services.control(Path(record["directory"]), "stop")
        deadline = time.monotonic() + 2
        while services.refresh(record)["state"] != "stopping":
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert services.control(Path(record["directory"]), "inspect")["state"] == "stopping"
        with pytest.raises(ManagementError, match="stopping"):
            services.start(registry, task, "group")
        # Another caller can complete stop while the original leader has exited.
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "lodex_cli.main",
                "service",
                "stop",
                "group",
                "--target",
                task["id"],
                "--json",
            ],
            env={**os.environ, "LODEX_HOME": str(registry.root)},
            capture_output=True,
            text=True,
            timeout=6,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        expected = "exited" if leader_exits else "stopped"
        assert json.loads(result.stdout)["result"]["state"] == expected
        assert (repo / "child-stopped").exists() is not ignore_term
        final = services.refresh(record)
        assert final["state"] == expected
        if leader_exits:
            assert final["exit_code"] == 7
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.killpg(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            pytest.fail("Service process group survived stop")
        (repo / "parent-exit").unlink(missing_ok=True)
        assert services.start(registry, task, "group")["state"] == "running"
    finally:
        try:
            services.stop(registry, task["id"], "group")
        except ManagementError:
            # Only this test's isolated group; prevents the regression leaking fixtures.
            import signal

            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
