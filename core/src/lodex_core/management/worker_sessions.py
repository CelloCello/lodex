"""One worker-session lock shared by launch admission and environment rebinding."""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from lodex_core.management.common import ManagementError, name, private_dir


@contextmanager
def session_lock(root: Path, task_id: str) -> Iterator[Path]:
    directory = root / "worker-sessions"
    task_id = name(task_id)
    private_dir(directory)
    with (directory / f"{task_id}.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ManagementError(
                "worker_active", "This taskenv already has an active worker"
            ) from exc
        try:
            yield directory / f"{task_id}.json"
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
