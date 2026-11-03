"""Opt-in real runtime fixtures. No coding-agent model is launched.

Requires explicit permission to start temporary isolated Herdr servers. Runtime
fixtures prove routing/lifecycle, not a real coding agent's effective permissions.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from lodex_cli import worker_policy
from lodex_core.management.common import ManagementError, read_json
from lodex_core.management.delegation import Client

from .test_service_delegation import delegated as delegated
from .test_worker_policy import draft as draft
from .test_worker_session import fixture_program

pytestmark = pytest.mark.skipif(
    os.environ.get("LODEX_TEST_HERDR_RUNTIME") != "1",
    reason="Opt-in temporary Herdr servers require explicit authorization",
)


@pytest.fixture(params=["tui", "core"])
def runtime(request: pytest.FixtureRequest) -> Iterator[tuple[str, dict[str, str], Path]]:
    kind = str(request.param)
    binary = shutil.which("herdr" if kind == "tui" else "hc")
    if binary is None:
        pytest.skip(f"{kind} runtime is not installed")
    with tempfile.TemporaryDirectory(prefix="ldr-", dir="/private/tmp") as directory:
        root = Path(directory)
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith(("HC_", "HERDR_"))
        }
        for part in ("CONFIG", "DATA", "CACHE", "STATE", "RUNTIME"):
            path = root / part.lower()
            path.mkdir()
            environment[f"XDG_{part}_HOME" if part != "RUNTIME" else "XDG_RUNTIME_DIR"] = str(path)
        environment["HC_SESSION"] = "lodex-fixture"
        environment["HC_SOCKET"] = str(root / "core.sock")
        environment["HERDR_SOCKET_PATH"] = str(root / "tui.sock")
        environment["HERDR_CONFIG_PATH"] = str(root / "config/herdr/config.toml")
        environment["HERDR_DISABLE_SOUND"] = "1"
        config = Path(environment["HERDR_CONFIG_PATH"])
        config.parent.mkdir()
        config.write_text(
            'onboarding=false\n[terminal]\ndefault_shell="/bin/sh"\nshell_mode="non_login"\n'
            "[session]\nresume_agents_on_restore=false\n"
        )
        process: subprocess.Popen[bytes] | None = None
        try:
            if kind == "tui":
                process = subprocess.Popen(
                    [binary, "server"],
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                deadline = time.monotonic() + 10
                while not Path(environment["HERDR_SOCKET_PATH"]).exists():
                    assert process.poll() is None, "Fixture Herdr server exited"
                    assert time.monotonic() < deadline, "Fixture Herdr socket did not appear"
                    time.sleep(0.05)
            else:
                result = subprocess.run(
                    [binary, "server", "start", "--json"],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                assert result.returncode == 0, result.stdout + result.stderr
            yield kind, environment, root
        finally:
            subprocess.run(
                [binary, "server", "stop"],
                env=environment,
                capture_output=True,
                timeout=20,
            )
            if process is not None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)


def invoke(binary: str, environment: dict[str, str], *arguments: str) -> Any:
    result = subprocess.run(
        [binary, *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    try:
        return json.loads(result.stdout)
    except ValueError:
        return result.stdout


@pytest.fixture
def managed_runtime(
    delegated: Any, runtime: tuple[str, dict[str, str], Path]
) -> tuple[str, dict[str, str], Path]:
    # Set up delegation first, so runtime teardown reaps guards before their
    # management directory is removed, including after a failed assertion.
    assert delegated["store"].root.is_dir()
    return runtime


def test_fixture_turns_keep_terminal_alive_and_cwd_explicit(
    runtime: tuple[str, dict[str, str], Path],
) -> None:
    kind, environment, root = runtime
    program = root / "interactive.py"
    program.write_text(
        "import os,sys,time\n"
        "print('cwd='+os.getcwd(),flush=True)\n"
        "for line in sys.stdin:\n"
        " if line.strip()=='exit': break\n"
        " time.sleep(.2)\n"
        " print('observed:'+line.strip(),flush=True)\n"
    )
    if kind == "tui":
        created = invoke("herdr", environment, "workspace", "create", "--cwd", str(root))
        pane = created["result"]["root_pane"]["pane_id"]
        import shlex

        invoke(
            "herdr",
            environment,
            "pane",
            "run",
            pane,
            shlex.join([sys.executable, "-u", str(program)]),
        )
        invoke(
            "herdr",
            environment,
            "pane",
            "wait-output",
            pane,
            "--match",
            "cwd=" + str(root),
            "--timeout",
            "10000",
        )
        for text in ("task-one", "direct-follow-up", "A-follow-up"):
            invoke("herdr", environment, "pane", "send-text", pane, text)
            invoke("herdr", environment, "pane", "send-keys", pane, "enter")
            invoke(
                "herdr",
                environment,
                "pane",
                "wait-output",
                pane,
                "--match",
                "observed:" + text,
                "--timeout",
                "10000",
            )
        invoke("herdr", environment, "pane", "close", pane)
    else:
        launched = invoke(
            "hc",
            environment,
            "run",
            "--bg",
            "--no-parent",
            "--cwd",
            str(root),
            "--name",
            "task-b",
            "--json",
            sys.executable,
            "-u",
            str(program),
        )
        terminal = launched["address"]
        assert isinstance(terminal, str), launched
        for text in ("task-one", "direct-follow-up", "A-follow-up"):
            invoke("hc", environment, "send", terminal, text, "--json")
            observed = invoke(
                "hc",
                environment,
                "wait",
                terminal,
                "--output",
                "observed:" + text,
                "--timeout",
                "5",
                "--json",
            )
            assert observed["reason"] == "output", observed
            state = invoke("hc", environment, "get", terminal, "--json")
            assert state["state"] == "live"
        invoke("hc", environment, "kill", terminal, "--json")


def test_actual_runtime_launches_guard_with_taskenv_cwd_and_first_task(
    managed_runtime: tuple[str, dict[str, str], Path], delegated: Any, draft: Any
) -> None:
    import shlex

    kind, environment, root = managed_runtime
    policy = draft["policy"]
    fixture_program(policy, root)
    task_file = root / "task.txt"
    task_file.write_text("Fixture first task; remain interactive for a follow-up")
    command = [
        *policy["launcher_argv"],
        "--policy",
        policy["policy_file"],
        "--runtime",
        kind,
        "--task-file",
        str(task_file),
    ]
    if kind == "tui":
        created = invoke("herdr", environment, "workspace", "create", "--cwd", policy["path"])
        pane = created["result"]["root_pane"]["pane_id"]
        before = invoke("herdr", environment, "pane", "current")
        split = invoke(
            "herdr",
            environment,
            "pane",
            "split",
            pane,
            "--direction",
            "right",
            "--cwd",
            policy["path"],
            "--no-focus",
        )
        target = split["result"]["pane"]["pane_id"]
        after = invoke("herdr", environment, "pane", "current")
        assert after["result"]["pane"]["pane_id"] == before["result"]["pane"]["pane_id"]
        invoke("herdr", environment, "pane", "run", target, shlex.join(command))
        invoke(
            "herdr",
            environment,
            "pane",
            "wait-output",
            target,
            "--match",
            "fixture-ready",
            "--timeout",
            "10000",
        )
        invoke("herdr", environment, "pane", "send-text", target, "direct-follow-up")
        invoke("herdr", environment, "pane", "send-keys", target, "enter")
        invoke(
            "herdr",
            environment,
            "pane",
            "wait-output",
            target,
            "--match",
            "fixture-reply:direct-follow-up",
            "--timeout",
            "10000",
        )
    else:
        launched = invoke(
            "hc",
            environment,
            "run",
            "--bg",
            "--no-parent",
            "--cwd",
            policy["path"],
            "--name",
            "guard-b",
            "--json",
            *command,
        )
        target = launched["address"]
        # Reading is observation, not readiness; the saved argument file below
        # is the fixture program's explicit acknowledgement of its first task.
        observed = invoke(
            "hc",
            environment,
            "wait",
            target,
            "--output",
            "fixture-ready",
            "--timeout",
            "5",
            "--json",
        )
        assert observed["reason"] != "exited", observed
    arguments = json.loads((Path(policy["path"]) / "fixture-arguments.json").read_text())
    assert arguments[-1] == task_file.read_text()
    record = read_json(delegated["store"].root / "worker-sessions" / f"{policy['taskenv']}.json")
    assert record["state"] == "running"
    assert record["runtime"]["kind"] == kind
    assert record["runtime"]["pane" if kind == "tui" else "terminal"] == target

    # Stop the first fixture agent, not just its turn, before renewing its grant.
    state_file = delegated["store"].root / "worker-sessions" / f"{policy['taskenv']}.json"
    if kind == "tui":
        invoke("herdr", environment, "pane", "send-text", target, "exit")
        invoke("herdr", environment, "pane", "send-keys", target, "enter")
        deadline = time.monotonic() + 5
        while read_json(state_file)["state"] == "running":
            assert time.monotonic() < deadline, "Old guard did not record its child's exit"
            time.sleep(0.02)
    else:
        invoke("hc", environment, "send", target, "exit", "--json")
        invoke("hc", environment, "wait", target, "--timeout", "5", "--json")
        assert invoke("hc", environment, "get", target, "--json")["state"] == "finished"
    assert read_json(state_file)["state"] == "exited"
    old_info, peer_info = delegated["infos"]
    peer = Client(Path(peer_info["credential_file"]))
    peer_service = peer.perform("start", "job", None)
    delegated["processes"][0].terminate()
    delegated["processes"][0].wait(timeout=5)
    fresh_grant = delegated["delegate"](delegated["tasks"][0])
    with pytest.raises(ManagementError):
        Client(Path(old_info["credential_file"])).request("list")
    fresh = worker_policy.render(
        delegated["store"],
        delegated["tasks"][0],
        **{**draft["arguments"], "delegation": fresh_grant["id"]},
    )
    fixture_program(fresh, root)
    native_session = str(uuid.uuid4())
    task_file.write_text(
        "Continue the fixture task from saved context; do not repeat completed work"
    )
    resumed = [
        *fresh["launcher_argv"],
        "--policy",
        fresh["policy_file"],
        "--runtime",
        kind,
        "--task-file",
        str(task_file),
        "--resume",
        native_session,
    ]
    if kind == "tui":
        new_pane = invoke(
            "herdr",
            environment,
            "pane",
            "split",
            pane,
            "--direction",
            "down",
            "--cwd",
            fresh["path"],
            "--no-focus",
        )["result"]["pane"]["pane_id"]
        invoke("herdr", environment, "pane", "run", new_pane, shlex.join(resumed))
        invoke(
            "herdr",
            environment,
            "pane",
            "wait-output",
            new_pane,
            "--match",
            "fixture-ready",
            "--timeout",
            "10000",
        )
        new_target = new_pane
    else:
        new_target = invoke(
            "hc",
            environment,
            "run",
            "--bg",
            "--no-parent",
            "--cwd",
            fresh["path"],
            "--name",
            "guard-b-resumed",
            "--json",
            *resumed,
        )["address"]
        observed = invoke(
            "hc",
            environment,
            "wait",
            new_target,
            "--output",
            "fixture-ready",
            "--timeout",
            "5",
            "--json",
        )
        assert observed["reason"] == "output", observed
    renewed = read_json(state_file)
    assert renewed["runtime"]["pane" if kind == "tui" else "terminal"] == new_target
    assert renewed["native_session"] == native_session and renewed["taskenv"] == policy["taskenv"]
    assert renewed["policy"] == fresh["id"]
    assert peer.request("inspect", "job")["pid"] == peer_service["pid"]
    if kind == "tui":
        invoke("herdr", environment, "pane", "send-text", new_target, "exit")
        invoke("herdr", environment, "pane", "send-keys", new_target, "enter")
        deadline = time.monotonic() + 5
        while read_json(state_file)["state"] == "running":
            assert time.monotonic() < deadline
            time.sleep(0.02)
    else:
        invoke("hc", environment, "send", new_target, "exit", "--json")
        invoke("hc", environment, "wait", new_target, "--timeout", "5", "--json")
        assert invoke("hc", environment, "get", new_target, "--json")["state"] == "finished"
    assert read_json(state_file)["state"] == "exited"
    peer.perform("stop", "job", None)


def test_core_controller_is_outside_worker_child_waits(
    runtime: tuple[str, dict[str, str], Path],
) -> None:
    kind, environment, _root = runtime
    if kind != "core":
        pytest.skip("Core-specific child wait contract")
    sleeper = [sys.executable, "-c", "import time;time.sleep(30)"]
    parent = invoke(
        "hc", environment, "run", "--bg", "--no-parent", "--name", "parent", "--json", *sleeper
    )["address"]
    controller = invoke(
        "hc",
        environment,
        "run",
        "--bg",
        "--no-parent",
        "--no-notify",
        "--name",
        "controller",
        "--json",
        *sleeper,
    )["address"]
    workers = []
    for name in ("b", "c"):
        argv = [
            sys.executable,
            "-u",
            "-c",
            "print('\\x1b]7501;state=done\\x07',flush=True);input()",
        ]
        workers.append(
            invoke(
                "hc",
                environment,
                "run",
                "--bg",
                "--parent",
                parent,
                "--outlive-parent",
                "--name",
                name,
                "--json",
                *argv,
            )["address"]
        )
    settled = invoke(
        "hc", environment, "wait", parent, "--children", "all", "--timeout", "2", "--json"
    )
    assert settled["reason"] != "timeout", settled
    for terminal in [controller, *workers]:
        assert invoke("hc", environment, "get", terminal, "--json")["state"] == "live"
    invoke("hc", environment, "kill", parent, "--json")
    for terminal in workers:
        assert invoke("hc", environment, "get", terminal, "--json")["state"] == "live"
