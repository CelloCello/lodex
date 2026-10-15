from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from lodex_core.management.project_config import load

EXAMPLE = Path(__file__).resolve().parents[1]
ROOT = EXAMPLE.parents[1]


def module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("fixture_validation", path)
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def proxy_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    requests: list[str] = []

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(503)
            self.end_headers()

    with ThreadingHTTPServer(("127.0.0.1", 0), Proxy) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        proxy = f"http://127.0.0.1:{server.server_port}"
        for key in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
            monkeypatch.setenv(key, proxy)
        for key in ("no_proxy", "NO_PROXY"):
            monkeypatch.setenv(key, "")
        monkeypatch.setattr(urllib.request, "_opener", None)
        try:
            yield requests
        finally:
            server.shutdown()
            thread.join()


def test_dual_environment_cli_acceptance_ignores_proxy(proxy_environment: list[str]) -> None:
    runner = module(ROOT / "scripts/verify_environments.py")
    summary = runner.verify(str(Path(sys.executable).parent / "lodex"))
    assert summary == {
        "environments": 2,
        "services_per_environment": 3,
        "isolation": True,
        "explicit_recovery": True,
    }
    assert proxy_environment == []


@pytest.mark.parametrize("timeout", [False, True], ids=["command-error", "timeout"])
def test_stop_services_continues_after_failure(timeout: bool) -> None:
    runner = module(ROOT / "scripts/verify_environments.py")
    stopped: list[str] = []

    def cli(*args: str) -> Any:
        assert args[-2:] == ("--target", "fixture-a")
        if args[:2] == ("service", "list"):
            return [{"name": name} for name in ("api", "queue", "worker")]
        assert args[:2] == ("service", "stop")
        stopped.append(args[2])
        if args[2] == "worker":
            if timeout:
                raise subprocess.TimeoutExpired(["lodex", *args], 30)
            raise RuntimeError("Worker supervisor unavailable")
        return {}

    with pytest.raises(RuntimeError, match=r"fixture-a.*worker"):
        runner.stop_services(cli, "fixture-a")
    assert stopped == ["worker", "queue", "api"]


def test_failed_stop_preserves_affected_taskenv_and_cleans_the_other(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = module(ROOT / "scripts/verify_environments.py")
    directory = tmp_path / "acceptance"
    directory.mkdir()

    @contextmanager
    def fixture_directory() -> Iterator[Path]:
        yield directory

    monkeypatch.setattr(runner, "fixture_directory", fixture_directory)
    original = runner.run
    tasks: list[dict[str, Any]] = []
    environment: dict[str, str] = {}
    executable = str(Path(sys.executable).parent / "lodex")

    def run(args: list[str], env: dict[str, str], cwd: Path, value: str | None = None) -> str:
        environment.update(env)
        if args[1:4] == ["service", "stop", "worker"] and tasks[0]["id"] in args:
            raise RuntimeError("Injected worker supervisor failure")
        output: str = original(args, env, cwd, value)
        if args[1:3] == ["worktree", "create"]:
            tasks.append(json.loads(output)["result"])
        return output

    monkeypatch.setattr(runner, "run", run)

    def cli(*args: str) -> Any:
        return json.loads(original([executable, *args, "--json"], environment, directory / "repo"))[
            "result"
        ]

    try:
        with pytest.raises(RuntimeError, match="Cleanup incomplete"):
            runner.verify(executable)
        a, b = tasks
        services = {
            item["name"]: item["state"] for item in cli("service", "list", "--target", a["id"])
        }
        assert services == {"api": "stopped", "queue": "stopped", "worker": "running"}
        assert (Path(a["path"]) / ".lodex/state/data.sqlite3").is_file()
        assert not Path(b["path"]).exists()
        assert all(
            item["state"] == "stopped" for item in cli("service", "list", "--target", b["id"])
        )
    finally:
        # Use the real CLI to release the worker intentionally left running by the test.
        for task in tasks:
            for name in reversed(runner.SERVICES):
                cli("service", "stop", name, "--target", task["id"])
            if Path(task["path"]).exists():
                if (Path(task["path"]) / ".lodex/state").exists():
                    cli("cleanup", "--target", task["id"])
                cli("worktree", "remove", "--target", task["id"], "--yes")


def test_fixture_declares_managed_services_and_private_state() -> None:
    config = load(EXAMPLE / "project.toml")
    assert set(config["services"]) == {"api", "queue", "worker"}
    assert set(config["commands"]) == {"prepare", "verify", "cleanup"}
    assert config["ports"] == {"API_PORT": 0, "QUEUE_PORT": 0}
    assert config["services"]["api"]["ready_port"] == "API_PORT"
    assert config["services"]["queue"]["ready_port"] == "QUEUE_PORT"
    assert "ready_port" not in config["services"]["worker"]
    assert (EXAMPLE / ".gitignore").read_text() == "/state/\n"


def test_cleanup_requires_matching_owner_and_verify_does_not_create_missing_db(
    tmp_path: Path,
) -> None:
    env = {**os.environ, "LODEX_WORKTREE": str(tmp_path), "LODEX_TASKENV_ID": "fixture-a"}

    def run(action: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(EXAMPLE / "fixture.py"), action],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
        )

    assert run("cleanup").returncode == 1
    assert run("prepare").returncode == 0
    state = tmp_path / ".lodex/state"
    database = state / "data.sqlite3"
    database.unlink()
    assert run("verify").returncode == 1 and not database.exists()
    assert run("prepare").returncode == 0
    marker = state / "owner.json"
    original = marker.read_text()
    marker.write_text(json.dumps({"taskenv": "different", "path": str(tmp_path)}))
    assert run("cleanup").returncode == 1 and database.exists()
    marker.write_text(original)
    assert run("cleanup").returncode == 0 and not state.exists()
