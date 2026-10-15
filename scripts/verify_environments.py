"""Exercise two self-contained multi-service taskenvs through the installed CLI."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("api", "queue", "worker")


def run(args: list[str], env: dict[str, str], cwd: Path, value: str | None = None) -> str:
    result = subprocess.run(
        args, env=env, cwd=cwd, input=value, capture_output=True, text=True, timeout=30
    )
    if result.returncode:
        raise RuntimeError(result.stdout[-2000:] + result.stderr[-1000:])
    return result.stdout


@contextmanager
def fixture_directory() -> Iterator[Path]:
    directory = Path(tempfile.mkdtemp(prefix="lodex-multi-service-")).resolve()
    try:
        yield directory
    except BaseException:
        print(f"Fixture retained for inspection: {directory}")
        raise
    else:
        shutil.rmtree(directory)


def stop_services(cli: Callable[..., Any], task_id: str) -> None:
    recorded = {service["name"] for service in cli("service", "list", "--target", task_id)}
    failures = []
    for name in reversed(SERVICES):
        if name in recorded:
            try:
                cli("service", "stop", name, "--target", task_id)
            except (RuntimeError, subprocess.TimeoutExpired):
                failures.append(name)
    if failures:
        raise RuntimeError(f"Failed to stop services for taskenv {task_id}: {', '.join(failures)}")


def verify(lodex: str = "lodex") -> dict[str, Any]:
    executable = shutil.which(lodex)
    if executable is None:
        raise RuntimeError("Install Lodex or pass --lodex /absolute/path/to/lodex")
    with fixture_directory() as directory:
        root = directory / "repo"
        integration = root / ".lodex"
        (integration / "scripts").mkdir(parents=True)
        example = ROOT / "examples/multi_service"
        for filename in ("project.toml", ".gitignore"):
            shutil.copyfile(example / filename, integration / filename)
        shutil.copyfile(example / "fixture.py", integration / "scripts/fixture.py")
        allowed = {"PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT"}
        env = {
            **{key: value for key, value in os.environ.items() if key in allowed},
            "LODEX_HOME": str(directory / "registry"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        for args in (
            ("init", "-q"),
            ("config", "user.name", "Fixture"),
            ("config", "user.email", "fixture@example.invalid"),
            ("config", "core.hooksPath", os.devnull),
            ("config", "core.excludesFile", os.devnull),
            ("add", ".lodex"),
            ("commit", "-qm", "Standalone multi-service fixture"),
        ):
            run(["git", *args], env, root)

        def cli(*args: str, value: str | None = None) -> Any:
            return json.loads(run([executable, *args, "--json"], env, root, value))["result"]

        token = secrets.token_hex(24)
        cli("secret", "set", "fixture-token", "--stdin", value=token)
        cli("project", "add", "multi-service", str(root))
        tasks: list[dict[str, Any]] = []
        http_client = build_opener(ProxyHandler({}))

        def http(task: dict[str, Any], service: str, path: str, payload: Any = None) -> Any:
            port = task["ports"]["API_PORT" if service == "api" else "QUEUE_PORT"]
            request = Request(
                f"http://127.0.0.1:{port}{path}",
                data=json.dumps(payload).encode() if payload is not None else None,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            with http_client.open(request, timeout=5) as response:
                return json.load(response)

        def processed(task: dict[str, Any], value: str) -> None:
            deadline = time.monotonic() + 5
            while http(task, "api", f"/values/{quote('processed:' + value)}")["value"] != value:
                if time.monotonic() >= deadline:
                    raise AssertionError("Worker did not process its taskenv's queue item")
                time.sleep(0.05)

        try:
            for branch in ("fixture-a", "fixture-b"):
                task = cli(
                    "worktree", "create", "multi-service", "--ref", "HEAD", "--branch", branch
                )
                tasks.append(task)
                assert cli("prepare", "--target", task["id"])["state"] == "succeeded"
                if branch == "fixture-a":
                    database = Path(task["path"]) / ".lodex/state/data.sqlite3"
                    database.rename(database.with_suffix(".missing"))
                    try:
                        cli("run", "verify", "--target", task["id"])
                    except RuntimeError:
                        pass
                    else:
                        raise AssertionError("Verify accepted a missing database")
                    failed = [
                        item
                        for item in cli("operation", "list", "--target", task["id"])
                        if item["state"] == "failed"
                    ]
                    assert len(failed) == 1 and failed[0]["exit_code"] == 1
                    assert cli("operation", "logs", failed[0]["id"])["tail"]
                    cli("prepare", "--target", task["id"])
                assert cli("run", "verify", "--target", task["id"])["state"] == "succeeded"
                for name in SERVICES:
                    assert (
                        cli("service", "start", name, "--target", task["id"])["state"] == "running"
                    )
                for name in ("api", "queue"):
                    assert http(task, name, "/health")["taskenv"] == task["id"]
                print(f"{branch}: prepared and all three services running", flush=True)
            a, b = tasks
            assert not set(a["ports"].values()) & set(b["ports"].values())
            http(a, "api", "/values/probe", {"value": "only-a"})
            assert http(b, "api", "/values/probe")["value"] is None
            http(a, "queue", "/items", {"value": "job-a"})
            processed(a, "job-a")
            assert http(b, "queue", "/items")["items"] == []
            assert http(b, "api", "/values/processed%3Ajob-a")["value"] is None
            # Keep an unconsumed item in B while cleaning A, then restart its worker.
            cli("service", "stop", "worker", "--target", b["id"])
            http(b, "queue", "/items", {"value": "keep-b"})
            stop_services(cli, a["id"])
            cleaned = cli("cleanup", "--target", a["id"])
            assert cleaned["state"] == "succeeded"
            assert {resource["state"] for resource in cleaned["result"]["resources"]} == {"removed"}
            assert not (Path(a["path"]) / ".lodex/state").exists()
            assert http(b, "queue", "/items")["items"] == [{"value": "keep-b", "done": False}]
            assert http(b, "api", "/health")["taskenv"] == b["id"]
            cli("service", "start", "worker", "--target", b["id"])
            processed(b, "keep-b")
            assert all(
                service["state"] == "running"
                for service in cli("service", "list", "--target", b["id"])
            )
            summary = {
                "environments": 2,
                "services_per_environment": len(SERVICES),
                "isolation": True,
                "explicit_recovery": True,
            }
            print("PASS: database/queue/port isolation; worker delivery; A cleanup preserves B")
            return summary
        finally:
            failures = []
            for task in tasks:
                try:
                    stop_services(cli, task["id"])
                    if (Path(task["path"]) / ".lodex/state").exists():
                        cli("cleanup", "--target", task["id"])
                    cli("worktree", "remove", "--target", task["id"], "--yes")
                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                    failures.append(f"{task['id']}: {exc}")
            if failures:
                raise RuntimeError(f"Cleanup incomplete for taskenvs {failures}; fixture retained")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lodex", default="lodex", help="Installed Lodex CLI executable")
    print(json.dumps(verify(parser.parse_args().lodex)))
