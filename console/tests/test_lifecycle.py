from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from lodex_core.management import worktrees
from lodex_core.management.project_config import CONFIG
from lodex_core.management.store import Registry


def test_console_shutdown_preserves_services_and_records_command_interruption(
    registry: Registry, repo: Path
) -> None:
    from lodex_core.management import operations, services

    (repo / CONFIG).write_text(
        "schema_version=1\n[commands.prepare]\nargv="
        + json.dumps([sys.executable, "parent.py"])
        + "\n[services.worker]\nargv="
        + json.dumps([sys.executable, "-c", "import time; time.sleep(60)"])
        + "\n"
    )
    (repo / "parent.py").write_text(
        "import os,subprocess,sys,time\nfrom pathlib import Path\n"
        "Path('command-pid').write_text(str(os.getpid()))\n"
        "subprocess.Popen([sys.executable,'-c',"
        + repr(
            "import signal,time; from pathlib import Path; "
            "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            "Path('descendant-ready').touch(); time.sleep(60)"
        )
        + "])\ntime.sleep(60)\n"
    )
    worktrees.project_add(registry, "sample", repo, None)
    task = worktrees.attach(registry, "sample", repo, None)
    services.start(registry, task, "worker")
    server = subprocess.Popen(
        [sys.executable, "-m", "lodex_cli.main", "console"],
        env={**os.environ, "LODEX_HOME": str(registry.root)},
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    command_group: int | None = None
    try:
        assert server.stdout
        url = server.stdout.readline().strip().removeprefix("Lodex console: ")
        origin, token = url.split("/#token=")
        headers = {"Authorization": f"Bearer {token}", "Origin": origin}
        for _ in range(100):
            try:
                if httpx.get(f"{origin}/api/state", headers=headers).status_code == 200:
                    break
            except httpx.ConnectError:
                time.sleep(0.05)
        else:
            pytest.fail("Console did not start")

        def prepare() -> None:
            try:
                httpx.post(
                    f"{origin}/api/action",
                    headers=headers,
                    json={"action": "prepare", "target": task["id"]},
                    timeout=15,
                )
            except httpx.HTTPError:
                pass

        with ThreadPoolExecutor() as pool:
            future = pool.submit(prepare)
            for _ in range(100):
                if (repo / "descendant-ready").exists():
                    break
                time.sleep(0.05)
            assert (repo / "descendant-ready").exists()
            command_group = int((repo / "command-pid").read_text())
            server.terminate()
            server.wait(timeout=12)
            future.result(timeout=5)
        records = registry.all("operation")
        assert len(records) == 1
        assert operations.inspect_operation(registry, records[0])["state"] in (
            "interrupted",
            "unknown",
        )
        assert services.list_services(registry, task["id"])[0]["state"] == "running"
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.killpg(command_group, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            pytest.fail("Console shutdown left repo descendants running")
    finally:
        if server.poll() is None:
            server.terminate()
            server.wait(timeout=12)
        services.stop(registry, task["id"], "worker")
        if command_group is not None:
            try:
                os.killpg(command_group, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
