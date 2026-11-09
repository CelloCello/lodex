from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from lodex_core.management import operations, project_config, services, worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.store import Registry
from lodex_core.management.worker_sessions import session_lock

from .support.management import register


def replacement(registry: Registry, repo: Path) -> dict[str, Any]:
    (repo / project_config.CONFIG).write_text(
        "schema_version=1\n[ports]\nPORT=0\n"
        '[commands.prepare]\nargv=["true"]\n[commands.verify]\nargv=["true"]\n'
        '[services.job]\nargv=["true"]\n'
    )
    register(registry, repo)
    task = worktrees.create(registry, "fixture", "HEAD", "old-branch")
    root = Path(task["path"])
    worktrees.git(repo, "worktree", "remove", "--force", str(root))
    other = repo.parent / "replacement"
    worktrees.git(repo, "worktree", "add", "-b", "new-branch", str(other), "HEAD")
    worktrees.git(repo, "worktree", "move", str(other), str(root))
    project_config.supply(root, repo / project_config.CONFIG)
    assert worktrees.identity(root)["git_dir"] != task["git_dir"]
    return task


def test_legacy_device_and_inode_values_do_not_affect_management(
    registry: Registry, repo: Path
) -> None:
    task = register(registry, repo)
    task.update(inode=[1, 2], git_inode=[3, 4], common_inode=[5, 6])
    registry.put("taskenv", task)
    project = registry.get("project", "fixture")
    project["common_inode"] = [7, 8]
    registry.put("project", project)
    assert worktrees.state(task) == "present"
    assert worktrees.require_present(task) == repo
    assert worktrees.attach(registry, "fixture", repo)["id"] == task["id"]
    assert worktrees.project_add(registry, "fixture", repo, None)["already_registered"]
    linked = worktrees.create(registry, "fixture", "HEAD", "after-reboot")
    assert worktrees.state(linked) == "present"
    assert not {"inode", "common_inode", "git_inode"} & linked.keys()
    worktrees.git(Path(linked["path"]), "switch", "-c", "different-branch")
    (Path(linked["path"]) / "README.md").write_text("dirty\n")
    assert worktrees.state(linked) == "present"
    assert worktrees.remove(registry, linked, yes=False, force=False)["git_status"]


def test_rebind_is_previewed_preserves_work_and_requires_new_prepare(
    registry: Registry, repo: Path
) -> None:
    task = replacement(registry, repo)
    root = Path(task["path"])
    (root / "README.md").write_text("keep dirty\n")
    (root / "untracked.txt").write_text("keep new\n")
    operation = {
        "id": "historical",
        "taskenv": task["id"],
        "command": "prepare",
        "state": "succeeded",
        "started_at": "2026-01-01",
        "observed_at": "2026-01-01",
        "result": {
            "resources": [
                {
                    "kind": "database",
                    "id": "old-db",
                    "name": "db",
                    "state": "present",
                    "scope": "exclusive",
                }
            ]
        },
    }
    registry.put("operation", operation)
    info = worktrees.inspect(registry, task)
    assert info["state"] == "identity_changed" and info["known_resources"][0]["id"] == "old-db"
    with pytest.raises(ManagementError) as changed:
        worktrees.attach(registry, "fixture", root)
    assert changed.value.details and changed.value.details["rebind"][-1] == "--rebind"
    config = root / project_config.CONFIG
    config.unlink()
    before = registry.all("taskenv")
    preview = worktrees.attach(registry, "fixture", root, rebind=True)
    assert not preview["rebound"] and preview["before"] != preview["after"]
    assert preview["previous_owned"] and not preview["owned"]
    assert registry.all("taskenv") == before and not config.exists()
    bound = worktrees.attach(registry, "fixture", root, rebind=True, yes=True)
    assert bound["id"] == task["id"] and bound["ports"] == task["ports"]
    assert bound["binding_revision"] == 1 and bound["prepare_required"] and not bound["owned"]
    assert worktrees.state(bound) == "present"
    assert registry.all("operation") == [operation]
    assert (root / "README.md").read_text() == "keep dirty\n"
    assert (root / "untracked.txt").read_text() == "keep new\n"
    assert worktrees.git(root, "branch", "--show-current") == "new-branch"
    assert worktrees.git(repo, "branch", "--list", "old-branch")
    with pytest.raises(ManagementError) as protected:
        worktrees.remove(registry, bound, yes=True, force=True)
    assert protected.value.code == "protected_checkout"
    with pytest.raises(ManagementError) as unprepared:
        operations.run(registry, bound, "verify")
    assert unprepared.value.code == "prepare_required"
    with pytest.raises(ManagementError, match="run prepare"):
        with registry.lock(bound["id"]):
            services.prepare_start(registry, bound, "job")
    prepared = operations.run(registry, bound, "prepare")
    assert prepared["state"] == "succeeded" and prepared["handoff"]["binding_revision"] == 1
    assert not registry.get("taskenv", bound["id"]).get("prepare_required")
    assert operations.run(registry, bound, "verify")["state"] == "succeeded"


@pytest.mark.parametrize("active", ["lock", "operation", "delegation", "service", "ack"])
def test_rebind_refuses_unresolved_work(
    registry: Registry, repo: Path, monkeypatch: pytest.MonkeyPatch, active: str
) -> None:
    task = replacement(registry, repo)
    if active == "operation":
        registry.put("operation", {"id": "op", "taskenv": task["id"], "state": "unknown"})
    elif active == "delegation":
        registry.put("service-delegation", {"id": "grant", "taskenv": task["id"], "active": True})
    elif active in ("service", "ack"):
        monkeypatch.setattr(
            services,
            "list_services",
            lambda *_: [
                {
                    "state": "running" if active == "service" else "stopped",
                    "pending_acks": active == "ack",
                }
            ],
        )
    before = registry.all("taskenv")
    if active == "lock":
        with registry.lock(task["id"]), pytest.raises(ManagementError, match="Another operation"):
            worktrees.attach(registry, "fixture", Path(task["path"]), rebind=True, yes=True)
    else:
        with pytest.raises(ManagementError) as blocked:
            worktrees.attach(registry, "fixture", Path(task["path"]), rebind=True, yes=True)
        assert blocked.value.code == ("unresolved_operations" if active == "operation" else "busy")
    assert registry.all("taskenv") == before


def test_unavailable_and_non_git_paths_retain_records(
    registry: Registry, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = register(registry, repo)
    original = worktrees.identity

    def denied(_: Path) -> dict[str, Any]:
        raise PermissionError("temporary permission failure")

    monkeypatch.setattr(worktrees, "identity", denied)
    assert worktrees.inspect(registry, task)["state"] == "unavailable"
    assert registry.get("taskenv", task["id"]) == task

    def missing_metadata(_: Path) -> dict[str, Any]:
        raise FileNotFoundError("Git metadata disappeared")

    monkeypatch.setattr(worktrees, "identity", missing_metadata)
    assert worktrees.observe(task)["state"] == "identity_changed"
    monkeypatch.setattr(worktrees, "identity", original)
    (repo / ".git").rename(repo / "saved-git")
    assert worktrees.inspect(registry, task)["state"] == "identity_changed"
    assert registry.get("taskenv", task["id"]) == task
    with pytest.raises(ManagementError):
        worktrees.require_present(task)


def test_failed_prepare_keeps_rebound_environment_unprepared(
    registry: Registry, repo: Path
) -> None:
    task = replacement(registry, repo)
    root = Path(task["path"])
    rebound = worktrees.attach(registry, "fixture", root, rebind=True, yes=True)
    config = root / project_config.CONFIG
    config.write_text(
        config.read_text().replace(
            '[commands.prepare]\nargv=["true"]', '[commands.prepare]\nargv=["false"]'
        )
    )
    assert operations.run(registry, rebound, "prepare")["state"] == "failed"
    assert registry.get("taskenv", task["id"])["prepare_required"]


def test_copied_git_pointer_cannot_be_accepted_by_rebind(registry: Registry, repo: Path) -> None:
    register(registry, repo)
    first = worktrees.create(registry, "fixture", "HEAD", "first")
    second = worktrees.create(registry, "fixture", "HEAD", "second")
    root = Path(first["path"])
    (root / ".git").write_bytes((Path(second["path"]) / ".git").read_bytes())
    assert worktrees.observe(first)["state"] == "identity_changed"
    with pytest.raises(ManagementError, match="points to another worktree"):
        worktrees.attach(registry, "fixture", root, rebind=True, yes=True)
    assert registry.get("taskenv", first["id"]) == first


def test_rebind_does_not_transfer_to_another_repository_or_create_registration(
    registry: Registry, repo: Path
) -> None:
    task = register(registry, repo)
    other = repo.parent / "other"
    worktrees.git(repo.parent, "clone", str(repo), str(other))
    with pytest.raises(ManagementError) as wrong:
        worktrees.attach(registry, "fixture", other, rebind=True, yes=True)
    assert wrong.value.code == "wrong_repository"
    detached = repo.parent / "detached"
    worktrees.git(repo, "worktree", "add", "--detach", str(detached), "HEAD")
    with pytest.raises(ManagementError) as absent:
        worktrees.attach(registry, "fixture", detached, rebind=True, yes=True)
    assert absent.value.code == "not_found"
    assert registry.all("taskenv") == [task]


def test_separate_git_dir_main_and_linked_worktrees(registry: Registry, repo: Path) -> None:
    metadata = repo.parent / "separate-metadata"
    worktrees.git(repo, "init", "-q", f"--separate-git-dir={metadata}")
    main = register(registry, repo)
    assert main["main"] and main["git_dir"] == str(metadata)
    assert worktrees.require_present(main) == repo
    assert worktrees.project_add(registry, "fixture", repo, None)["already_registered"]
    assert worktrees.attach(registry, "fixture", repo)["id"] == main["id"]
    linked = worktrees.create(registry, "fixture", "HEAD", "linked-separate")
    assert not linked["main"] and worktrees.state(linked) == "present"
    with pytest.raises(ManagementError) as protected:
        worktrees.remove(registry, main, yes=True, force=True)
    assert protected.value.code == "protected_checkout"


def test_rebind_acknowledges_unknown_outcome_without_rewriting_history(
    registry: Registry, repo: Path
) -> None:
    program = (
        "import os; from pathlib import Path; "
        'Path(os.environ["LODEX_RESULT_FILE"]).write_text("invalid json")'
    )
    (repo / project_config.CONFIG).write_text(
        'schema_version=1\n[commands.prepare]\nargv=["true"]\n'
        "[commands.bad_result]\nargv=" + json.dumps([sys.executable, "-c", program]) + "\n"
    )
    task = register(registry, repo)
    bad = operations.run(registry, task, "bad_result")
    assert bad["state"] == "unknown" and bad["exit_code"] == 0
    assert operations.run(registry, task, "prepare")["state"] == "succeeded"
    preview = worktrees.attach(registry, "fixture", repo, rebind=True)
    assert preview["required_acknowledgements"] == [bad["id"]]
    assert preview["unresolved_operations"][0]["error"] == "invalid_result"
    with pytest.raises(ManagementError) as blocked:
        worktrees.attach(registry, "fixture", repo, rebind=True, yes=True)
    assert blocked.value.code == "unresolved_operations"
    with pytest.raises(ManagementError) as foreign:
        worktrees.attach(
            registry,
            "fixture",
            repo,
            rebind=True,
            yes=True,
            acknowledge_operations=["another-environment-operation"],
        )
    assert foreign.value.code == "invalid_input"
    with registry.lock(f"op-{bad['id']}"), pytest.raises(ManagementError) as active:
        worktrees.attach(
            registry, "fixture", repo, rebind=True, yes=True, acknowledge_operations=[bad["id"]]
        )
    assert active.value.code == "busy"
    bound = worktrees.attach(
        registry, "fixture", repo, rebind=True, yes=True, acknowledge_operations=[bad["id"]]
    )
    assert bound["id"] == task["id"] and bound["binding_revision"] == 1
    assert bad["id"] in bound["rebind_acknowledgements"]
    assert registry.get("operation", bad["id"]) == bad
    assert not worktrees.attach(registry, "fixture", repo, rebind=True)["required_acknowledgements"]


def test_lost_running_operation_can_be_acknowledged_after_its_lock_is_released(
    registry: Registry, repo: Path
) -> None:
    task = register(registry, repo)
    lost = {"id": "lost", "taskenv": task["id"], "state": "running"}
    registry.put("operation", lost)
    preview = worktrees.attach(registry, "fixture", repo, rebind=True)
    assert preview["unresolved_operations"][0]["state"] == "unknown"
    assert preview["required_acknowledgements"] == ["lost"]
    result = worktrees.attach(
        registry, "fixture", repo, rebind=True, yes=True, acknowledge_operations=["lost"]
    )
    assert result["rebound"] and registry.get("operation", "lost") == lost


def test_rebind_refuses_live_and_unconfirmed_workers(registry: Registry, repo: Path) -> None:
    task = replacement(registry, repo)
    before = registry.get("taskenv", task["id"])
    with session_lock(registry.root, task["id"]) as record:
        record.write_text(json.dumps({"state": "running"}))
        with pytest.raises(ManagementError) as live:
            worktrees.attach(registry, "fixture", Path(task["path"]), rebind=True, yes=True)
        assert live.value.code == "worker_active"
    with pytest.raises(ManagementError) as unknown:
        worktrees.attach(registry, "fixture", Path(task["path"]), rebind=True, yes=True)
    assert unknown.value.code == "worker_unknown"
    assert registry.get("taskenv", task["id"]) == before
    record.write_text(json.dumps({"state": "exited"}))
    assert worktrees.attach(registry, "fixture", Path(task["path"]), rebind=True, yes=True)[
        "rebound"
    ]
