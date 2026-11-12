"""One worker-session lock shared by launch admission and environment rebinding."""

from __future__ import annotations

import fcntl
import json
import os
import uuid
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from lodex_core.management.common import (
    ManagementError,
    name,
    now,
    private_dir,
    read_json,
    write_private,
)
from lodex_core.management.store import Registry

TERMINAL_STATES = {"exited", "launch_failed", "reconciled"}


@contextmanager
def session_lock(root: Path, task_id: str, *, child_fds: list[int] | None = None) -> Iterator[Path]:
    directory = root / "worker-sessions"
    task_id = name(task_id)
    private_dir(directory)
    # The inherited lease grants no write handle to central state.
    descriptor = os.open(directory / f"{task_id}.lock", os.O_CREAT | os.O_RDONLY, 0o600)
    with os.fdopen(descriptor, "r") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ManagementError(
                "worker_active", "This taskenv already has an active worker"
            ) from exc
        if child_fds is not None:
            child_fds.append(stream.fileno())
        # Close our descriptor instead of LOCK_UN: an admitted child inherits
        # the same open description and retains the lock if its guard dies.
        yield directory / f"{task_id}.json"


@contextmanager
def inactive_session(root: Path, task_id: str) -> Iterator[None]:
    """Exclude new launches until the protected registry change is published."""
    with session_lock(root, task_id) as record:
        if record.exists() and read_json(record).get("state") not in TERMINAL_STATES:
            raise ManagementError(
                "worker_unknown", f"Confirm the previous worker exited: {task_id}"
            )
        yield


def reconcile(
    registry: Registry,
    task: dict[str, Any],
    *,
    yes: bool = False,
    record_id: str | None = None,
    evidence: str | None = None,
) -> dict[str, Any]:
    """Record an explicit manager attestation; never infer exit from a stale PID.

    A free lock is necessary, not sufficient: older/third-party agents may not
    retain inherited descriptors. The operator must inspect the saved runtime.
    """
    with registry.lock(task["id"]), ExitStack() as held:
        # Preview must remain available while the old writer is alive so the
        # manager can locate its runtime. Only confirmation acquires its lease.
        path = registry.root / "worker-sessions" / f"{name(task['id'])}.json"
        if yes:
            path = held.enter_context(session_lock(registry.root, task["id"]))
        registry.reload_task(task)
        if not path.exists():
            raise ManagementError("not_found", "No worker session record for this taskenv")
        previous = read_json(path)
        result = {
            "taskenv": task["id"],
            "worker": previous,
            "reconciled": False,
            "warning": (
                "Inspect the saved runtime and confirm the old agent and unmanaged writers exited. "
                "A free lock alone is not proof."
            ),
        }
        if not yes:
            return result
        if previous.get("state") not in {"running", "unknown"}:
            raise ManagementError(
                "worker_state", "Only an unconfirmed worker exit needs reconciliation"
            )
        if (
            not record_id
            or previous.get("id") != record_id
            or previous.get("taskenv") != task["id"]
        ):
            raise ManagementError(
                "worker_record_changed", "Use the current worker record ID from preview"
            )
        if not evidence or not evidence.strip() or len(evidence) > 4096:
            raise ManagementError(
                "worker_evidence", "Provide 1-4096 characters describing verified exit evidence"
            )
        receipt = {
            "id": uuid.uuid4().hex,
            "taskenv": task["id"],
            "previous": previous,
            "evidence": evidence.strip(),
            "confirmed_at": now(),
        }
        # Persist the confirmation before admitting another writer. A failed
        # record write leaves admission blocked; the audit survives later runs.
        registry.put("worker-reconciliation", receipt)
        updated = {**previous, "state": "reconciled", "reconciliation": receipt["id"]}
        write_private(path, json.dumps(updated))
        return {**result, "worker": updated, "reconciled": True, "receipt": receipt}
