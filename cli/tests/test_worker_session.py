from __future__ import annotations

import json
import os
import selectors
import shutil
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from lodex_cli import worker_policy, worker_session
from lodex_core.management.common import ManagementError, write_private

from .test_service_delegation import delegated as delegated
from .test_worker_policy import draft as draft


def fixture_program(policy: dict[str, Any], directory: Path) -> None:
    program = directory / "interactive.py"
    program.write_text(
        "import json,sys,time\nfrom pathlib import Path\n"
        "Path('fixture-arguments.json').write_text(json.dumps(sys.argv[1:]))\n"
        "time.sleep(.2)\nprint('fixture-ready',flush=True)\n"
        "for line in sys.stdin:\n"
        " if line.strip()=='exit': break\n"
        " print('fixture-reply:'+line.strip(),flush=True)\n"
    )
    policy["agent_argv"] = [sys.executable, "-u", str(program), *policy["agent_argv"][1:]]
    write_private(Path(policy["policy_file"]), json.dumps(policy))


def record_native_session(policy: dict[str, Any]) -> str:
    identity = str(uuid.uuid4())
    path = Path(policy["launch_env"]["CODEX_HOME"]) / "sessions" / f"rollout-{identity}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": identity, "cwd": policy["path"]}})
        + "\n"
    )
    return identity


def launch(
    policy: dict[str, Any], task_file: Path, kind: str, resume: str | None = None
) -> subprocess.Popen[str]:
    environment = {
        **os.environ,
        "HC_TERMINAL_ID": "t-fixture",
        "HC_SESSION": "isolated-fixture",
        "HERDR_ENV": "1",
        "HERDR_SOCKET_PATH": "/fixture/herdr.sock",
        "HERDR_WORKSPACE_ID": "w-fixture",
        "HERDR_TAB_ID": "w-fixture:t1",
        "HERDR_PANE_ID": "w-fixture:p1",
    }
    command = [
        *policy["launcher_argv"],
        "--policy",
        policy["policy_file"],
        "--runtime",
        kind,
        "--task-file",
        str(task_file),
    ]
    if resume is not None:
        command.extend(["--resume", resume])
    return subprocess.Popen(
        command,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def line(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(timeout=10), "Fixture did not respond"
    return str(process.stdout.readline().strip())


def finish(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.communicate("exit\n", timeout=10)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


@pytest.mark.parametrize("kind", ["tui", "core"])
def test_launch_guard_preserves_interaction_and_resumes_after_new_grant(
    delegated: Any, draft: Any, tmp_path: Path, kind: str
) -> None:
    policy = draft["policy"]
    task_file = tmp_path / "handoff.txt"
    task_file.write_text("Fixture task: complete one turn and wait for follow-up")
    fixture_program(policy, tmp_path)
    first = launch(policy, task_file, kind)
    try:
        assert line(first) == "fixture-ready"
        assert first.stdin is not None
        for instruction in ("first-turn", "direct-user-follow-up", "A-follow-up"):
            first.stdin.write(instruction + "\n")
            first.stdin.flush()
            assert line(first) == "fixture-reply:" + instruction
            assert first.poll() is None
        duplicate = launch(policy, task_file, kind)
        _, error = duplicate.communicate(timeout=10)
        assert duplicate.returncode == 1 and "active worker" in error
    finally:
        finish(first)
    assert first.returncode == 0
    root = delegated["store"].root
    state_file = root / "worker-sessions" / f"{policy['taskenv']}.json"
    state = json.loads(state_file.read_text())
    assert state["state"] == "exited" and state["runtime"]["kind"] == kind
    assert state["policy"] == policy["id"]
    delegated["processes"][0].terminate()
    delegated["processes"][0].wait(timeout=5)
    replacement = delegated["delegate"](delegated["tasks"][0])
    fresh = worker_policy.render(
        delegated["store"],
        delegated["tasks"][0],
        **{**draft["arguments"], "delegation": replacement["id"]},
    )
    fixture_program(fresh, tmp_path)
    native_session = record_native_session(fresh)
    task_file.write_text("Continue from the saved task state; do not repeat completed steps")
    resumed = launch(fresh, task_file, kind, native_session)
    try:
        assert line(resumed) == "fixture-ready"
        arguments = json.loads((Path(policy["path"]) / "fixture-arguments.json").read_text())
        assert arguments[-4:] == ["resume", native_session, "--", task_file.read_text()]
        assert any(fresh["permission_profile"] in arg for arg in arguments)
        assert not any(policy["permission_profile"] in arg for arg in arguments)
        updated = json.loads(state_file.read_text())
        assert updated["policy"] == fresh["id"]
        assert updated["taskenv"] == state["taskenv"]
        assert updated["native_session"] == native_session
    finally:
        finish(resumed)


def test_unknown_exit_does_not_automatically_launch_second_writer(
    delegated: Any, draft: Any, tmp_path: Path
) -> None:
    policy = draft["policy"]
    task_file = tmp_path / "handoff.txt"
    task_file.write_text("Fixture task")
    fixture_program(policy, tmp_path)
    state_file = delegated["store"].root / "worker-sessions" / f"{policy['taskenv']}.json"
    write_private(state_file, json.dumps({"state": "running", "runtime": {"terminal": "t-old"}}))
    process = launch(policy, task_file, "core", str(uuid.uuid4()))
    _, error = process.communicate(timeout=10)
    assert process.returncode == 1 and "Previous exit is unconfirmed" in error
    assert json.loads(state_file.read_text())["runtime"]["terminal"] == "t-old"


@pytest.mark.parametrize("kind", ["tui", "core"])
@pytest.mark.parametrize("state", ["exited", "launch_failed"])
def test_resume_rejects_another_native_session_without_changing_saved_records(
    delegated: Any, draft: Any, tmp_path: Path, kind: str, state: str
) -> None:
    policy = draft["policy"]
    task_file = tmp_path / "task.txt"
    task_file.write_text("Continue the original conversation only")
    fixture_program(policy, tmp_path)
    directory = delegated["store"].root / "worker-sessions"
    state_file = directory / f"{policy['taskenv']}.json"
    peer_file = directory / f"{delegated['tasks'][1]['id']}.json"
    native_session, peer_session = str(uuid.uuid4()), str(uuid.uuid4())
    write_private(state_file, json.dumps({"state": state, "native_session": native_session}))
    write_private(peer_file, json.dumps({"state": "running", "native_session": peer_session}))
    original, peer_original = state_file.read_bytes(), peer_file.read_bytes()

    rejected = launch(policy, task_file, kind, peer_session)
    _, error = rejected.communicate(timeout=10)
    assert rejected.returncode == 1 and "does not match" in error
    assert state_file.read_bytes() == original
    assert peer_file.read_bytes() == peer_original
    assert not (Path(policy["path"]) / "fixture-arguments.json").exists()

    resumed = launch(policy, task_file, kind, native_session)
    try:
        assert line(resumed) == "fixture-ready"
        arguments = json.loads((Path(policy["path"]) / "fixture-arguments.json").read_text())
        assert arguments[-4:] == ["resume", native_session, "--", task_file.read_text()]
    finally:
        finish(resumed)
    assert json.loads(state_file.read_text())["native_session"] == native_session
    assert peer_file.read_bytes() == peer_original


@pytest.mark.parametrize("kind", ["tui", "core"])
def test_resume_matches_uuid_identity_across_equivalent_spellings(
    delegated: Any, draft: Any, tmp_path: Path, kind: str
) -> None:
    policy = draft["policy"]
    task_file = tmp_path / "task.txt"
    task_file.write_text("Continue the same UUID using canonical spelling")
    fixture_program(policy, tmp_path)
    state_file = delegated["store"].root / "worker-sessions" / f"{policy['taskenv']}.json"
    native_session = str(uuid.uuid4())
    write_private(
        state_file, json.dumps({"state": "exited", "native_session": native_session.upper()})
    )
    resumed = launch(policy, task_file, kind, native_session.replace("-", ""))
    try:
        assert line(resumed) == "fixture-ready"
        arguments = json.loads((Path(policy["path"]) / "fixture-arguments.json").read_text())
        assert arguments[-4:] == ["resume", native_session, "--", task_file.read_text()]
    finally:
        finish(resumed)
    assert json.loads(state_file.read_text())["native_session"] == native_session


@pytest.mark.parametrize("kind", ["tui", "core"])
@pytest.mark.parametrize("state", [None, "exited", "launch_failed"])
def test_first_resume_rejects_unverified_candidates_then_accepts_own_session(
    delegated: Any, draft: Any, tmp_path: Path, kind: str, state: str | None
) -> None:
    policy = draft["policy"]
    task_file = tmp_path / "task.txt"
    task_file.write_text("Resume the verified original conversation")
    state_file = delegated["store"].root / "worker-sessions" / f"{policy['taskenv']}.json"
    if state is not None:
        write_private(state_file, json.dumps({"state": state, "native_session": None}))
    original = state_file.read_bytes() if state_file.exists() else None
    native_session = record_native_session(policy)
    peer_session = record_native_session({**policy, "path": delegated["tasks"][1]["path"]})
    policy["agent_argv"] = [
        sys.executable,
        "-I",
        "-c",
        "from pathlib import Path;Path('unexpected-child').touch();raise SystemExit(2)",
    ]
    write_private(Path(policy["policy_file"]), json.dumps(policy))

    for candidate in (str(uuid.uuid4()), peer_session):
        rejected = launch(policy, task_file, kind, candidate)
        _, error = rejected.communicate(timeout=10)
        assert rejected.returncode == 1 and "not recorded for this taskenv" in error
        assert (state_file.read_bytes() if state_file.exists() else None) == original
        assert not (Path(policy["path"]) / "unexpected-child").exists()

    profile = draft["codex_home"] / "fixture.config.toml"
    configuration = profile.read_text()
    profile.write_text(configuration + f"sqlite_home={json.dumps(str(tmp_path))}\n")
    try:
        rejected = launch(policy, task_file, kind, native_session)
        _, error = rejected.communicate(timeout=10)
        assert rejected.returncode == 1 and "Cannot verify" in error
        assert (state_file.read_bytes() if state_file.exists() else None) == original
        assert not (Path(policy["path"]) / "unexpected-child").exists()
    finally:
        profile.write_text(configuration)

    fixture_program(policy, tmp_path)
    resumed = launch(policy, task_file, kind, native_session)
    try:
        assert line(resumed) == "fixture-ready"
        assert json.loads(state_file.read_text())["native_session"] == native_session
        duplicate = launch(policy, task_file, kind, native_session)
        _, error = duplicate.communicate(timeout=10)
        assert duplicate.returncode == 1 and "active worker" in error
    finally:
        finish(resumed)
    assert json.loads(state_file.read_text())["native_session"] == native_session


@pytest.mark.parametrize("kind", ["tui", "core"])
@pytest.mark.parametrize("resuming", [False, True])
def test_known_spawn_failure_can_retry_without_losing_resume_requirement(
    delegated: Any, draft: Any, tmp_path: Path, kind: str, resuming: bool
) -> None:
    policy = draft["policy"]
    task_file = tmp_path / "task.txt"
    task_file.write_text("Continue only after the reviewed launch is repaired")
    native_session = record_native_session(policy) if resuming else None
    state_file = delegated["store"].root / "worker-sessions" / f"{policy['taskenv']}.json"
    if resuming:
        write_private(state_file, json.dumps({"state": "exited"}))
    policy["agent_argv"] = [str(tmp_path / "missing-codex")]
    write_private(Path(policy["policy_file"]), json.dumps(policy))
    failed = launch(policy, task_file, kind, native_session)
    failed.communicate(timeout=10)
    assert failed.returncode == 1
    assert json.loads(state_file.read_text())["state"] == "launch_failed"
    assert json.loads(state_file.read_text())["native_session"] == native_session

    fixture_program(policy, tmp_path)
    if resuming:
        fresh = launch(policy, task_file, kind)
        _, error = fresh.communicate(timeout=10)
        assert fresh.returncode == 1 and "native session ID" in error
    retried = launch(policy, task_file, kind, native_session)
    try:
        assert line(retried) == "fixture-ready"
        arguments = json.loads((Path(policy["path"]) / "fixture-arguments.json").read_text())
        assert ("resume" in arguments) == resuming
        if resuming:
            assert arguments[-4:] == ["resume", native_session, "--", task_file.read_text()]
        duplicate = launch(policy, task_file, kind, native_session)
        _, error = duplicate.communicate(timeout=10)
        assert duplicate.returncode == 1 and "active worker" in error
    finally:
        finish(retried)
    assert json.loads(state_file.read_text())["state"] == "exited"
    fresh = launch(policy, task_file, kind)
    _, error = fresh.communicate(timeout=10)
    assert fresh.returncode == 1 and "native session ID" in error


def test_wait_failure_keeps_exit_unknown_and_blocks_another_writer(
    delegated: Any, draft: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = draft["policy"]
    task_file = tmp_path / "task.txt"
    task_file.write_text("Fixture task")
    monkeypatch.setenv("HC_TERMINAL_ID", "t-fixture")
    child = Mock()
    child.wait.side_effect = OSError("Exit could not be confirmed")
    spawn = Mock(return_value=child)
    original = subprocess.Popen

    def launch_child(arguments: list[str], **kwargs: Any) -> Any:
        if arguments == [*policy["agent_argv"], "--", task_file.read_text()]:
            return spawn(arguments, **kwargs)
        return original(arguments, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", launch_child)
    with pytest.raises(OSError):
        worker_session.run(Path(policy["policy_file"]), "core", task_file)
    state_file = delegated["store"].root / "worker-sessions" / f"{policy['taskenv']}.json"
    assert json.loads(state_file.read_text())["state"] == "running"
    with pytest.raises(ManagementError) as blocked:
        worker_session.run(Path(policy["policy_file"]), "core", task_file)
    assert blocked.value.code == "worker_unknown"
    spawn.assert_called_once()


@pytest.mark.parametrize("kind", ["tui", "core"])
@pytest.mark.parametrize("resuming", [False, True])
def test_exit_before_native_session_allows_only_initial_launch_to_retry(
    delegated: Any, draft: Any, tmp_path: Path, kind: str, resuming: bool
) -> None:
    policy = draft["policy"]
    task_file = tmp_path / "task.txt"
    task_file.write_text("Retry only a confirmed pre-session startup failure")
    state_file = delegated["store"].root / "worker-sessions" / f"{policy['taskenv']}.json"
    native_session = record_native_session(policy) if resuming else None
    if resuming:
        write_private(state_file, json.dumps({"state": "exited"}))
    policy["agent_argv"] = [sys.executable, "-I", "-c", "raise SystemExit(2)"]
    write_private(Path(policy["policy_file"]), json.dumps(policy))
    failed = launch(policy, task_file, kind, native_session)
    failed.communicate(timeout=10)
    assert failed.returncode == 2
    saved = json.loads(state_file.read_text())
    assert saved["state"] == "exited" and saved["native_session"] == native_session
    assert (saved.get("native_admission") == "absent") == (not resuming)

    fixture_program(policy, tmp_path)
    if resuming:
        fresh = launch(policy, task_file, kind)
        _, error = fresh.communicate(timeout=10)
        assert fresh.returncode == 1 and "native session ID" in error
    retried = launch(policy, task_file, kind, native_session)
    try:
        assert line(retried) == "fixture-ready"
        duplicate = launch(policy, task_file, kind, native_session)
        _, error = duplicate.communicate(timeout=10)
        assert duplicate.returncode == 1 and "active worker" in error
        saved = json.loads(state_file.read_text())
        assert saved["runtime"]["kind"] == kind and saved["native_session"] == native_session
    finally:
        finish(retried)
    fresh = launch(policy, task_file, kind)
    _, error = fresh.communicate(timeout=10)
    assert fresh.returncode == 1 and "native session ID" in error


@pytest.mark.parametrize(
    "evidence",
    [
        "rollout",
        "archived",
        "state_db",
        "redirect",
        "unverifiable",
        "writable",
        "success",
        "signal",
        "legacy",
    ],
)
def test_missing_uuid_alone_never_authorizes_fresh_retry(
    delegated: Any, draft: Any, tmp_path: Path, evidence: str
) -> None:
    policy = draft["policy"]
    home = draft["codex_home"]
    task_file = tmp_path / "task.txt"
    task_file.write_text("Do not replace an existing or uncertain conversation")
    state_file = delegated["store"].root / "worker-sessions" / f"{policy['taskenv']}.json"
    code = "raise SystemExit(2)"
    if evidence in {"rollout", "archived", "state_db"}:
        target = (
            home
            / {
                "rollout": "sessions/new/malformed.jsonl",
                "archived": "archived_sessions/new.jsonl",
                "state_db": "state_5.sqlite",
            }[evidence]
        )
        code = (
            "from pathlib import Path\n"
            f"p=Path({str(target)!r});p.parent.mkdir(parents=True,exist_ok=True)\n"
            "p.write_text('opaque native storage');raise SystemExit(2)"
        )
    elif evidence == "redirect":
        (home / "fixture.config.toml").write_text(f"sqlite_home={json.dumps(str(tmp_path))}")
    elif evidence == "unverifiable":
        (home / "sessions").symlink_to(tmp_path, target_is_directory=True)
    elif evidence == "writable":
        policy["filesystem"][str(home)] = "write"
    elif evidence == "success":
        code = "pass"
    elif evidence == "signal":
        code = "import os,signal;os.kill(os.getpid(),signal.SIGTERM)"
    elif evidence == "legacy":
        write_private(state_file, json.dumps({"state": "exited", "exit_code": 2}))
    if evidence != "legacy":
        policy["agent_argv"] = [sys.executable, "-I", "-c", code]
        write_private(Path(policy["policy_file"]), json.dumps(policy))
        failed = launch(policy, task_file, "core")
        failed.communicate(timeout=10)
    before_retry = state_file.read_bytes()
    fresh = launch(policy, task_file, "core")
    _, error = fresh.communicate(timeout=10)
    assert fresh.returncode == 1 and "native session ID" in error
    assert state_file.read_bytes() == before_retry


@pytest.mark.parametrize("kind", ["tui", "core"])
@pytest.mark.skipif(
    shutil.which("codex") is None, reason="Installed Codex required for native parser integration"
)
def test_actual_codex_argument_error_can_retry_without_a_native_uuid(
    delegated: Any, draft: Any, tmp_path: Path, kind: str
) -> None:
    policy = draft["policy"]
    task_file = tmp_path / "task.txt"
    task_file.write_text("Fixture only; no model calls")
    policy["agent_argv"].append("--lodex-fixture-invalid-startup-argument")
    write_private(Path(policy["policy_file"]), json.dumps(policy))
    failed = launch(policy, task_file, kind)
    _, error = failed.communicate(timeout=10)
    assert failed.returncode == 2 and "unexpected argument" in error
    assert not list(draft["codex_home"].rglob("rollout-*.jsonl"))
    saved = json.loads(
        (delegated["store"].root / "worker-sessions" / f"{policy['taskenv']}.json").read_text()
    )
    assert saved["native_admission"] == "absent"
    fixture_program(policy, tmp_path)
    retried = launch(policy, task_file, kind)
    try:
        assert line(retried) == "fixture-ready"
    finally:
        finish(retried)


@pytest.mark.parametrize("existing", [False, True])
def test_peer_native_history_changes_do_not_block_initial_retry(
    delegated: Any, draft: Any, tmp_path: Path, existing: bool
) -> None:
    policy = draft["policy"]
    home = draft["codex_home"]
    peer = delegated["tasks"][1]["path"]
    identity = str(uuid.uuid4())
    with sqlite3.connect(home / "state_5.sqlite") as connection:
        connection.execute("CREATE TABLE threads(id TEXT,cwd TEXT)")
        if existing:
            connection.execute("INSERT INTO threads VALUES(?,?)", (identity, peer))
    with sqlite3.connect(home / "thread_history_1.sqlite") as connection:
        connection.execute("CREATE TABLE thread_items(thread_id TEXT,item_json TEXT)")
        if existing:
            connection.execute("INSERT INTO thread_items VALUES(?,?)", (identity, "private body"))
    header = json.dumps({"type": "session_meta", "payload": {"id": identity, "cwd": peer}})
    path = home / "sessions/peer.jsonl"
    path.parent.mkdir()
    if existing:
        path.write_text(header + "\n")
    before = worker_session.native_storage(policy)
    assert before is not None
    path.write_text(header + "\nchanged peer turn body, not parsed\n")
    with sqlite3.connect(home / "state_5.sqlite") as connection:
        if not existing:
            connection.execute("INSERT INTO threads VALUES(?,?)", (identity, peer))
    with sqlite3.connect(home / "thread_history_1.sqlite") as connection:
        connection.execute(
            "INSERT INTO thread_items VALUES(?,?)", (identity, "another private body")
        )
    assert worker_session.native_storage(policy) == before


@pytest.mark.parametrize("storage", ["rollout", "state", "orphan", "new_schema"])
def test_native_storage_never_reports_existing_or_unknown_history_as_absent(
    delegated: Any, draft: Any, tmp_path: Path, storage: str
) -> None:
    policy = draft["policy"]
    home = draft["codex_home"]
    identity = str(uuid.uuid4())
    if storage == "rollout":
        p = home / "sessions/own.jsonl"
        p.parent.mkdir()
        p.write_text(
            json.dumps({"type": "session_meta", "payload": {"id": identity, "cwd": policy["path"]}})
            + "\n"
        )
    elif storage == "state":
        with sqlite3.connect(home / "state_5.sqlite") as connection:
            connection.execute("CREATE TABLE threads(id TEXT,cwd TEXT)")
            connection.execute("INSERT INTO threads VALUES(?,?)", (identity, policy["path"]))
    else:
        with sqlite3.connect(home / "thread_history_1.sqlite") as connection:
            if storage == "orphan":
                connection.execute("CREATE TABLE thread_items(thread_id TEXT)")
            else:
                connection.execute("CREATE TABLE unrecognized_native_sessions(id TEXT)")
    task_file = tmp_path / "task.txt"
    task_file.write_text("Do not lose earlier context")
    code = "raise SystemExit(2)"
    if storage == "orphan":
        code = (
            "import sqlite3\n"
            f"c=sqlite3.connect({str(home / 'thread_history_1.sqlite')!r})\n"
            f"c.execute('INSERT INTO thread_items VALUES(?)',({identity!r},))\n"
            "c.commit();c.close()\n"
            "raise SystemExit(2)"
        )
    policy["agent_argv"] = [sys.executable, "-I", "-c", code]
    write_private(Path(policy["policy_file"]), json.dumps(policy))
    first = launch(policy, task_file, "core")
    first.communicate(timeout=10)
    state = json.loads(
        (delegated["store"].root / "worker-sessions" / f"{policy['taskenv']}.json").read_text()
    )
    assert state["native_admission"] == "unknown"
    second = launch(policy, task_file, "core")
    _, error = second.communicate(timeout=10)
    assert second.returncode == 1 and "native session ID" in error


@pytest.mark.parametrize("indexed", [False, True])
def test_compressed_native_headers_use_index_or_bounded_existing_decompressor(
    draft: Any, indexed: bool
) -> None:
    policy, home = draft["policy"], draft["codex_home"]
    identity = str(uuid.uuid4())
    path = home / "sessions" / f"rollout-{identity}.jsonl.zst"
    path.parent.mkdir()
    if indexed:
        with sqlite3.connect(home / "state_5.sqlite") as connection:
            connection.execute("CREATE TABLE threads(id TEXT,cwd TEXT)")
            connection.execute("INSERT INTO threads VALUES(?,?)", (identity, policy["path"]))
        # An indexed rollout needs no decompression or body parsing.
        path.write_bytes(b"opaque compressed body")
    else:
        zstd = shutil.which("zstd")
        if zstd is None:
            pytest.skip("Optional decompressor is unavailable")
        header = {
            "type": "session_meta",
            "payload": {
                "id": identity,
                "cwd": policy["path"],
                "base_instructions": "x" * 100000,
            },
        }
        content = json.dumps(header).encode() + b"\nbody is never parsed\n"
        path.write_bytes(
            subprocess.run([zstd, "-cq"], input=content, capture_output=True, check=True).stdout
        )
    observed = worker_session.native_storage(policy)
    assert observed is not None and observed["native_ids"] == [identity]


def test_unreadable_native_store_is_unknown(draft: Any) -> None:
    directory = draft["codex_home"] / "sessions"
    directory.mkdir()
    directory.chmod(0)
    try:
        assert worker_session.native_storage(draft["policy"]) is None
    finally:
        directory.chmod(0o700)


def test_native_decoder_never_executes_worker_controlled_path(
    delegated: Any, draft: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    zstd = shutil.which("zstd")
    if zstd is None:
        pytest.skip("Optional decompressor is unavailable")
    policy, home = draft["policy"], draft["codex_home"]
    marker = delegated["store"].root / "decoder-marker"
    marker.write_text("untouched")
    directory = Path(policy["path"]) / "bin"
    directory.mkdir()
    malicious = directory / "zstd"
    malicious.write_text(
        f"#!{sys.executable}\nimport os\nfrom pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('escaped')\n"
        f"os.execl({zstd!r},{zstd!r},'-dc')\n"
    )
    malicious.chmod(0o700)
    identity = str(uuid.uuid4())
    header = json.dumps(
        {"type": "session_meta", "payload": {"id": identity, "cwd": policy["path"]}}
    )
    compressed = subprocess.run(
        [zstd, "-cq"],
        input=header.encode() + b"\n",
        capture_output=True,
        check=True,
    ).stdout
    path = home / "sessions" / f"rollout-{identity}.jsonl.zst"
    path.parent.mkdir()
    path.write_bytes(compressed)
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + os.environ.get("PATH", ""))
    observed = worker_session.native_storage(policy)
    assert observed is not None and observed["native_ids"] == [identity]
    assert marker.read_text() == "untouched"


@pytest.mark.parametrize("resuming", [False, True])
def test_task_text_cannot_be_interpreted_as_native_cli_options(
    delegated: Any, draft: Any, tmp_path: Path, resuming: bool
) -> None:
    policy = draft["policy"]
    fixture_program(policy, tmp_path)
    task_file = tmp_path / "task.txt"
    task_file.write_text("--dangerously-bypass-approvals-and-sandbox")
    native = record_native_session(policy) if resuming else None
    if resuming:
        write_private(
            delegated["store"].root / "worker-sessions" / f"{policy['taskenv']}.json",
            json.dumps({"state": "exited"}),
        )
    process = launch(policy, task_file, "core", native)
    try:
        assert line(process) == "fixture-ready"
        arguments = json.loads((Path(policy["path"]) / "fixture-arguments.json").read_text())
        assert arguments[-2:] == ["--", task_file.read_text()]
    finally:
        finish(process)
