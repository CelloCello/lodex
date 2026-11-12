from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from lodex_core.management import worktrees
from lodex_core.management.common import ManagementError, write_private
from lodex_core.management.store import Registry
from lodex_core.management.worker_sessions import reconcile, session_lock


@pytest.fixture
def abandoned(registry: Registry, repo: Path) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    (repo / ".lodex/project.toml").write_text("schema_version=1\n")
    worktrees.project_add(registry, "sample", repo, None)
    task = worktrees.create(registry, "sample", "HEAD", "abandoned")
    with session_lock(registry.root, task["id"]) as path:
        record = {
            "id": "lost-launch",
            "taskenv": task["id"],
            "state": "running",
            "native_session": "retained-uuid",
            "exit_code": None,
            "runtime": {"kind": "core", "socket": "/observed/socket", "terminal": "t-test"},
        }
        write_private(path, json.dumps(record))
    return task, path, record


def test_reconciliation_preview_and_stale_confirmation_are_nonmutating(
    registry: Registry, abandoned: Any
) -> None:
    task, path, record = abandoned
    before = path.read_bytes()
    preview = reconcile(registry, task)
    assert preview["worker"] == record and not preview["reconciled"]
    for record_id, evidence, code in (
        (None, "checked", "worker_record_changed"),
        ("another-launch", "checked", "worker_record_changed"),
        (record["id"], " ", "worker_evidence"),
    ):
        with pytest.raises(ManagementError) as error:
            reconcile(registry, task, yes=True, record_id=record_id, evidence=evidence)
        assert error.value.code == code
        assert path.read_bytes() == before
        assert registry.all("worker-reconciliation") == []
    with session_lock(registry.root, task["id"]):
        assert reconcile(registry, task)["worker"] == record
        with pytest.raises(ManagementError) as busy:
            reconcile(registry, task, yes=True, record_id=record["id"], evidence="checked")
        assert busy.value.code == "worker_active"


@pytest.mark.parametrize("action", ["remove", "forget", "rebind"])
def test_confirmed_exit_unblocks_retirement_or_rebind_and_retains_audit(
    registry: Registry, abandoned: Any, action: str
) -> None:
    task, path, record = abandoned
    result = reconcile(
        registry,
        task,
        yes=True,
        record_id=record["id"],
        evidence="Verified saved terminal and all its writers exited",
    )
    updated = json.loads(path.read_text())
    assert updated["state"] == "reconciled"
    assert updated["native_session"] == record["native_session"]
    assert updated["exit_code"] is None  # Do not invent an observed exit code.
    receipt = registry.get("worker-reconciliation", updated["reconciliation"])
    assert receipt["previous"] == record
    assert result["receipt"] == receipt
    if action == "remove":
        worktrees.remove(registry, task, yes=True, force=True)
    elif action == "forget":
        worktrees.forget(registry, task, yes=True)
    else:
        assert worktrees.attach(registry, "sample", Path(task["path"]), rebind=True, yes=True)[
            "rebound"
        ]
    assert registry.get("worker-reconciliation", receipt["id"]) == receipt


def test_audit_failure_does_not_release_unknown_worker(
    registry: Registry, abandoned: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    task, path, record = abandoned
    before = path.read_bytes()

    def fail(*args: Any) -> None:
        raise OSError("audit storage unavailable")

    monkeypatch.setattr(registry, "put", fail)
    with pytest.raises(OSError):
        reconcile(registry, task, yes=True, record_id=record["id"], evidence="checked")
    assert path.read_bytes() == before


def test_inherited_lease_does_not_grant_central_file_write_access(
    registry: Registry, abandoned: Any
) -> None:
    task, _, _ = abandoned
    descriptors: list[int] = []
    with session_lock(registry.root, task["id"], child_fds=descriptors):
        with pytest.raises(OSError):
            os.write(descriptors[0], b"must not alter central state")
