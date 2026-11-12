"""Interactive launch guard used by the Herdr skill, not an agent scheduler.

Run inside a terminal created by the chosen runtime. This process holds a local
taskenv lock until its child exits. It never controls Herdr or executes repo
recipes. Unknown previous exits require reconciliation rather than a retry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tomllib
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from lodex_cli import worker_policy
from lodex_core.management.common import ManagementError, now, read_json, write_private
from lodex_core.management.delegation import KIND, Client
from lodex_core.management.environment import process_env
from lodex_core.management.store import Registry
from lodex_core.management.worker_sessions import TERMINAL_STATES, session_lock


def native_storage(policy: dict[str, Any]) -> dict[str, Any] | None:
    """Conservative metadata receipt for the inspected local Codex storage layout.

    Only IDs, cwd, row counts and bounded rollout headers are inspected.
    Unreadable/redirected stores and changes for this checkout are unknown.
    """
    home = Path(policy["launch_env"]["CODEX_HOME"])
    root = Path(policy["path"])
    configs = [home / "config.toml", home / f"{policy['profile']}.config.toml"]
    configs.extend(p / ".codex/config.toml" for p in (*root.parents, root))
    try:
        home_info = home.lstat()
        if not stat.S_ISDIR(home_info.st_mode):
            return None
        entries = list(home.iterdir())
        if any(
            mode == "write" and (home.is_relative_to(Path(path)) or Path(path).is_relative_to(home))
            for path, mode in policy["filesystem"].items()
        ):
            return None
        if os.environ.get("CODEX_SQLITE_HOME") or any(
            arg == "--remote" or arg.startswith(("--remote=", "sqlite_home=", "thread_store="))
            for arg in policy["agent_argv"]
        ):
            return None
        for path in configs:
            if path.exists():
                data = tomllib.loads(path.read_text())
                if set(data) & {"sqlite_home", "thread_store", "session_store"}:
                    return None
        observed: dict[str, Any] = {"home": (home_info.st_dev, home_info.st_ino)}
        identities: dict[str, str] = {}
        inspected = 0

        def database(path: Path) -> sqlite3.Connection:
            if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError("Unknown native database")
            return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.2)

        # State IDs identify most rollouts without opening their headers. The
        # state index also covers IDs before/without a legacy rollout file.
        for path in entries:
            if not (path.name.startswith("state_") and path.suffix == ".sqlite"):
                continue
            if path.name != "state_5.sqlite":
                raise ValueError("Unknown native state version")
            with closing(database(path)) as connection:
                rows = connection.execute("SELECT id,cwd FROM threads").fetchmany(20001)
                if len(rows) > 20000:
                    raise ValueError("Native state scan limit")
                for identity, cwd in rows:
                    if (
                        not isinstance(identity, str)
                        or not isinstance(cwd, str)
                        or not Path(cwd).is_absolute()
                    ):
                        raise ValueError("Unknown native ID")
                    uuid.UUID(identity)
                    identities[identity] = str(Path(cwd).resolve())

        def visit(path: Path) -> None:
            nonlocal inspected
            inspected += 1
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not (
                stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
            ):
                raise ValueError("Unverifiable native storage")
            if inspected > 20000:
                raise ValueError("Native storage scan limit")
            if path.is_dir():
                for child in path.iterdir():
                    visit(child)
                return
            if not (path.name.endswith(".jsonl") or path.name.endswith(".jsonl.zst")):
                raise ValueError("Unknown native session format")
            identity = path.name.removesuffix(".zst").removesuffix(".jsonl")[-36:]
            if identity not in identities:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as stream:
                    if path.suffix == ".zst":
                        environment = process_env({})
                        writable = [
                            Path(p).resolve()
                            for p, mode in policy["filesystem"].items()
                            if mode == "write"
                        ]
                        environment["PATH"] = os.pathsep.join(
                            str(Path(p).resolve())
                            for p in environment.get("PATH", "").split(os.pathsep)
                            if Path(p).is_absolute()
                            and not any(Path(p).resolve().is_relative_to(w) for w in writable)
                        )
                        zstd = shutil.which("zstd", path=environment["PATH"])
                        if zstd is None:
                            raise ValueError("Compressed native history is not indexed")
                        executable = Path(zstd).resolve()
                        if any(executable.is_relative_to(w) for w in writable):
                            raise ValueError("Native decoder is worker-writable")
                        # Optional existing decompressor, trusted env, bounded
                        # header only. Always reap it, including parse failures.
                        with subprocess.Popen(
                            [str(executable), "-dc"],
                            stdin=stream,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL,
                            env=environment,
                        ) as reader:
                            try:
                                assert reader.stdout is not None
                                raw = reader.stdout.readline(1024 * 1024 + 1)
                            finally:
                                if reader.poll() is None:
                                    reader.terminate()
                    else:
                        raw = stream.readline(1024 * 1024 + 1)
                    header = json.loads(raw)
                payload = header["payload"]
                identity, cwd = payload["id"], payload["cwd"]
                if (
                    header["type"] != "session_meta"
                    or not isinstance(cwd, str)
                    or not Path(cwd).is_absolute()
                    or not isinstance(identity, str)
                ):
                    raise ValueError("Unknown native session header")
                uuid.UUID(identity)
                identities[identity] = str(Path(cwd).resolve())
            if identities[identity] == str(root):
                observed[str(path)] = (
                    info.st_dev,
                    info.st_ino,
                    info.st_size,
                    info.st_mtime_ns,
                    info.st_ctime_ns,
                )

        for name in ("sessions", "archived_sessions"):
            directory = home / name
            if directory.exists() or directory.is_symlink():
                visit(directory)

        owned = sorted(identity for identity, cwd in identities.items() if cwd == str(root))
        observed["native_ids"] = owned
        for path in entries:
            if not (path.name.startswith("thread_history_") and path.suffix == ".sqlite"):
                continue
            if path.name != "thread_history_1.sqlite":
                raise ValueError("Unknown native history version")
            with closing(database(path)) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                } - {"_sqlx_migrations"}
                if tables - {
                    "thread_turns",
                    "thread_items",
                    "thread_history_projection_state",
                    "thread_realtime_items",
                }:
                    raise ValueError("Unknown native history schema")
                for table in sorted(tables):
                    counts = connection.execute(
                        f'SELECT thread_id,COUNT(*) FROM "{table}" GROUP BY thread_id'
                    ).fetchmany(20001)
                    if len(counts) > 20000:
                        raise ValueError("Native history scan limit")
                    for identity, _count in counts:
                        if not isinstance(identity, str):
                            raise ValueError("Unknown native history ID")
                        uuid.UUID(identity)
                    observed[str(path) + ":" + table] = sorted(
                        (identity, count)
                        for identity, count in counts
                        if identity in owned or identity not in identities
                    )
        return observed
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, RecursionError):
        return None


def runtime_context(kind: str) -> dict[str, str]:
    if kind == "tui":
        if os.environ.get("HERDR_ENV") != "1" or not os.environ.get("HERDR_PANE_ID"):
            raise ManagementError("runtime_context", "Launch inside the selected Herdr TUI pane")
        return {
            "kind": "tui",
            "socket": os.environ.get("HERDR_SOCKET_PATH", ""),
            "workspace": os.environ.get("HERDR_WORKSPACE_ID", ""),
            "tab": os.environ.get("HERDR_TAB_ID", ""),
            "pane": os.environ["HERDR_PANE_ID"],
        }
    if not os.environ.get("HC_TERMINAL_ID"):
        raise ManagementError("runtime_context", "Launch inside the selected herdr-core terminal")
    return {
        "kind": "core",
        "machine": os.uname().nodename,
        "session": os.environ.get("HC_SESSION", ""),
        "socket": os.environ.get("HC_SOCKET", ""),
        "terminal": os.environ["HC_TERMINAL_ID"],
    }


def run(policy_path: Path, kind: str, task_file: Path, resume: str | None = None) -> int:
    if os.name != "posix":
        raise ManagementError("runtime_platform", "This launch guard requires POSIX advisory locks")
    runtime = runtime_context(kind)
    if resume is not None:
        try:
            resume = str(uuid.UUID(resume))
        except ValueError as exc:
            raise ManagementError(
                "native_session", "Pass the observed native session UUID, not --last"
            ) from exc
    if policy_path.parent.name != "worker-policies":
        raise ManagementError("worker_policy", "Select a protected Lodex worker policy")
    store = Registry(policy_path.parent.parent, read_only=True)
    try:
        raw = read_json(policy_path)
        task = store.get("taskenv", raw["taskenv"])
        child_fds: list[int] = []
        with session_lock(store.root, task["id"], child_fds=child_fds) as record_path:
            policy = worker_policy.read(store, task, policy_path)
            if policy["delegation"] is not None:
                grant = store.get(KIND, policy["delegation"])
                if not grant["active"] or grant["taskenv"] != task["id"]:
                    raise ManagementError(
                        "delegation_revoked", "Review and render the new delegation"
                    )
                Client(Path(policy["routes"]["LODEX_SERVICE_DELEGATION"])).request(
                    "list", target=task["id"]
                )
            # The task is supplied explicitly by A, not copied from a shared conversation.
            prompt = task_file.read_text()
            if not prompt.strip():
                raise ManagementError("task_prompt", "Provide the task and handoff context")
            saved_session = None
            if record_path.exists():
                previous = read_json(record_path)
                if previous["state"] not in TERMINAL_STATES:
                    raise ManagementError(
                        "worker_unknown",
                        "Previous exit is unconfirmed; inspect its saved runtime before recovery",
                    )
                saved_session = previous.get("native_session")
                if resume is not None and saved_session is not None:
                    try:
                        saved_session = str(uuid.UUID(saved_session))
                    except (ValueError, TypeError, AttributeError) as exc:
                        raise ManagementError(
                            "native_session", "Cannot verify the saved native session UUID"
                        ) from exc
                    if resume != saved_session:
                        raise ManagementError(
                            "session_resume_mismatch",
                            "Requested native session UUID does not match "
                            "this taskenv's saved session",
                        )
                if resume is None and (
                    previous.get("native_session") is not None
                    or not (
                        previous["state"] == "launch_failed"
                        or (
                            previous["state"] == "exited"
                            and isinstance(previous.get("exit_code"), int)
                            and previous["exit_code"] > 0
                            and previous.get("native_admission") == "absent"
                        )
                    )
                ):
                    raise ManagementError(
                        "session_resume_required", "Use the observed native session ID to continue"
                    )
            if resume is not None and saved_session is None:
                observed = native_storage(policy)
                if observed is None:
                    raise ManagementError(
                        "native_session_unverified",
                        "Cannot verify this taskenv's native session storage",
                    )
                if resume not in {str(uuid.UUID(identity)) for identity in observed["native_ids"]}:
                    raise ManagementError(
                        "native_session_scope",
                        "Native session UUID is not recorded for this taskenv",
                    )
            arguments = list(policy["agent_argv"])
            if resume is not None:
                arguments.extend(["resume", resume])
            arguments.extend(["--", prompt])
            record: dict[str, Any] = {
                "id": uuid.uuid4().hex,
                "taskenv": task["id"],
                "policy": policy["id"],
                "policy_file": str(policy_path),
                "runtime": runtime,
                "native_session": resume,
                "task_digest": hashlib.sha256(prompt.encode()).hexdigest(),
                "state": "running",
                "started_at": now(),
                "exit_code": None,
            }
            write_private(record_path, json.dumps(record))
            child: subprocess.Popen[bytes] | None = None
            watched = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
            original = {sig: signal.getsignal(sig) for sig in watched}

            def interrupted(signum: int, frame: object) -> None:
                # Terminal Ctrl+C already reaches both processes in their foreground
                # group. Keep the guard alive while the interactive agent handles it.
                if signum != signal.SIGINT and child is not None and child.poll() is None:
                    child.send_signal(signum)

            try:
                for sig in watched:
                    signal.signal(sig, interrupted)
                before = native_storage(policy) if resume is None else None
                child = subprocess.Popen(
                    arguments,
                    cwd=task["path"],
                    env={**os.environ, **policy["launch_env"]},
                    pass_fds=child_fds,
                )
                record["exit_code"] = child.wait()
                record["state"] = "exited"
                if resume is None and record["exit_code"] > 0:
                    after = native_storage(policy)
                    record["native_admission"] = (
                        "absent"
                        if before is not None and before == after and not before["native_ids"]
                        else "unknown"
                    )
                    record["native_storage_check"] = {
                        "method": "codex-local-metadata-v1",
                        "before": hashlib.sha256(
                            json.dumps(before, sort_keys=True).encode()
                        ).hexdigest()
                        if before is not None
                        else None,
                        "after": hashlib.sha256(
                            json.dumps(after, sort_keys=True).encode()
                        ).hexdigest()
                        if after is not None
                        else None,
                    }
            except OSError:
                if child is None:
                    record.update(state="launch_failed", exit_code=1)
                raise
            finally:
                for sig, handler in original.items():
                    signal.signal(sig, handler)
                record["observed_at"] = now()
                write_private(record_path, json.dumps(record))
            return int(record["exit_code"])
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--runtime", required=True, choices=("tui", "core"))
    parser.add_argument("--task-file", required=True, type=Path)
    parser.add_argument("--resume")
    args = parser.parse_args()
    try:
        return run(args.policy, args.runtime, args.task_file, args.resume)
    except (ManagementError, OSError) as exc:
        print(f"lodex worker launch: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
