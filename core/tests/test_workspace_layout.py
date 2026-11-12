from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lodex_core.management import worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.store import Registry
from lodex_core.management.worker_sessions import session_lock
from lodex_core.management.workspace import configured_root, runtime_base, validate_checkout


@pytest.mark.parametrize("suffix", ["", ".git/workspaces"])
def test_root_cannot_be_inside_project_before_first_task(
    registry: Registry, repo: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    worktrees.project_add(registry, "sample", repo, None)
    monkeypatch.setenv("LODEX_WORKSPACE_ROOT", str(repo / suffix))
    before = worktrees.git(repo, "worktree", "list", "--porcelain")
    with pytest.raises(ManagementError) as error:
        worktrees.create(registry, "sample", "HEAD", "unsafe")
    assert error.value.code == "workspace_config"
    assert registry.all("taskenv") == []
    assert worktrees.git(repo, "worktree", "list", "--porcelain") == before


def test_project_local_root_is_allowed_without_making_source_a_worker(
    registry: Registry, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / ".lodex/project.toml").write_text("schema_version=1\n")
    worktrees.project_add(registry, "sample", repo, None)
    monkeypatch.setenv("LODEX_WORKSPACE_ROOT", str(repo / ".workspaces"))
    task = worktrees.create(registry, "sample", "HEAD", "local-root")
    assert Path(task["path"]).is_relative_to(repo / ".workspaces")
    with pytest.raises(ManagementError) as error:
        worktrees.attach(registry, "sample", repo)
    assert error.value.code == "workspace_overlap"


def test_attach_checks_saved_roots_even_after_configuration_changes(
    registry: Registry, repo: Path
) -> None:
    (repo / ".lodex/project.toml").write_text("schema_version=1\n")
    worktrees.project_add(registry, "sample", repo, None)
    peer = worktrees.create(registry, "sample", "HEAD", "peer")
    # Model a registration accepted by the old version. The current default is
    # safe, but attaching this root would expose the peer's saved runtime.
    peer["workspace_root"] = str(repo)
    registry.put("taskenv", peer)
    marker = runtime_base(registry, peer) / "marker"
    marker.parent.mkdir(parents=True)
    marker.write_text("untouched")
    with pytest.raises(ManagementError) as error:
        worktrees.attach(registry, "sample", repo)
    assert error.value.code == "workspace_overlap"
    assert registry.all("taskenv") == [peer]
    assert marker.read_text() == "untouched"


@pytest.mark.parametrize("register_parent_first", [True, False])
def test_nested_attach_checks_worker_and_holds_lease_until_publication(
    registry: Registry, repo: Path, monkeypatch: pytest.MonkeyPatch, register_parent_first: bool
) -> None:
    (repo / ".lodex/project.toml").write_text("schema_version=1\n")
    worktrees.project_add(registry, "sample", repo, None)
    child = repo / "nested"
    worktrees.git(repo, "worktree", "add", "--detach", str(child), "HEAD")
    first, second = (repo, child) if register_parent_first else (child, repo)
    peer = worktrees.attach(registry, "sample", first)

    with session_lock(registry.root, peer["id"]) as record:
        with pytest.raises(ManagementError) as busy:
            worktrees.attach(registry, "sample", second)
        assert busy.value.code == "worker_active"
        record.write_text(json.dumps({"state": "running"}))
    with pytest.raises(ManagementError) as unknown:
        worktrees.attach(registry, "sample", second)
    assert unknown.value.code == "worker_unknown"
    assert registry.all("taskenv") == [peer]

    record.write_text(json.dumps({"state": "reconciled"}))
    with registry.lock(peer["id"]), pytest.raises(ManagementError) as in_operation:
        worktrees.attach(registry, "sample", second)
    assert in_operation.value.code == "busy"
    put = registry.put

    def publish(kind: str, item: dict[str, Any]) -> None:
        # Simulate a competing guard at the last instant before the new row is visible.
        with pytest.raises(ManagementError) as racing, session_lock(registry.root, peer["id"]):
            pytest.fail("worker admitted during registration")
        assert racing.value.code == "worker_active"
        put(kind, item)

    monkeypatch.setattr(registry, "put", publish)
    nested = worktrees.attach(registry, "sample", second)
    assert worktrees.resolve(registry, str(second))["id"] == nested["id"]
    with session_lock(registry.root, peer["id"]), pytest.raises(ManagementError) as overlap:
        validate_checkout(registry, peer, worker=True)
    assert overlap.value.code == "workspace_overlap"


@pytest.mark.parametrize(
    "location",
    [
        ".r/nested",
        "delegation-sockets/nested",
        "legacy/worker-runtime/nested",
        "legacy/delegated/nested",
    ],
)
def test_attach_rejects_reserved_runtime_namespace(
    registry: Registry, repo: Path, location: str
) -> None:
    (repo / ".lodex/project.toml").write_text("schema_version=1\n")
    worktrees.project_add(registry, "sample", repo, None)
    peer = worktrees.create(registry, "sample", "HEAD", "peer")
    if location.startswith("legacy/"):
        parent = registry.root
        location = location.removeprefix("legacy/")
    else:
        parent = Path(peer["workspace_root"])
    nested = parent / location
    worktrees.git(repo, "worktree", "add", "--detach", str(nested), "HEAD")
    with pytest.raises(ManagementError) as error:
        worktrees.attach(registry, "sample", nested)
    assert error.value.code == "workspace_overlap"
    assert registry.all("taskenv") == [peer]


def test_configuration_changes_only_new_environments(
    registry: Registry, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / ".lodex/project.toml").write_text("schema_version=1\n")
    worktrees.project_add(registry, "sample", repo, None)
    first = worktrees.create(registry, "sample", "HEAD", "first")
    saved = dict(first)
    custom = tmp_path / "custom workspaces"
    (registry.root / "management.toml").write_text(f"workspace_root={json.dumps(str(custom))}\n")
    second = worktrees.create(registry, "sample", "HEAD", "second")
    assert Path(second["path"]).is_relative_to(custom)
    assert registry.get("taskenv", first["id"]) == saved
    assert runtime_base(registry, first).is_relative_to(Path(first["workspace_root"]))
    assert not runtime_base(registry, first).is_relative_to(registry.root)
    monkeypatch.setenv("LODEX_WORKSPACE_ROOT", str(tmp_path / "override"))
    assert configured_root(registry) == tmp_path / "override"
    assert runtime_base(registry, second).is_relative_to(custom)
    assert worktrees.resolve(registry, first["path"])["id"] == first["id"]


@pytest.mark.parametrize("value", ["", "relative", "inside", "ancestor", "symlink"])
def test_reject_ambiguous_or_overlapping_roots(
    registry: Registry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    if value == "inside":
        value = str(registry.root / "projects")
    elif value == "ancestor":
        value = str(registry.root.parent)
    elif value == "symlink":
        link = tmp_path / "linked"
        link.symlink_to(registry.root, target_is_directory=True)
        value = str(link)
    monkeypatch.setenv("LODEX_WORKSPACE_ROOT", value)
    with pytest.raises(ManagementError) as error:
        configured_root(registry)
    assert error.value.code == "workspace_config"


def test_legacy_records_and_runtime_are_not_migrated(registry: Registry, repo: Path) -> None:
    (repo / ".lodex/project.toml").write_text("schema_version=1\n")
    worktrees.project_add(registry, "sample", repo, None)
    path = registry.root / "projects/sample/legacy"
    worktrees.git(repo, "worktree", "add", "-b", "legacy", str(path), "HEAD")
    task = worktrees.attach(registry, "sample", path, owned=True)
    task.pop("workspace_root")
    registry.put("taskenv", task)
    before = json.dumps(task, sort_keys=True)
    assert worktrees.attach(registry, "sample", path) == task
    assert runtime_base(registry, task) == registry.root
    assert json.dumps(registry.get("taskenv", task["id"]), sort_keys=True) == before


@pytest.mark.parametrize("action", ["remove", "forget"])
def test_retirement_cannot_race_worker_or_discard_unknown_exit(
    registry: Registry, repo: Path, action: str
) -> None:
    (repo / ".lodex/project.toml").write_text("schema_version=1\n")
    worktrees.project_add(registry, "sample", repo, None)
    task = worktrees.create(registry, "sample", "HEAD", "retire")

    def retire() -> None:
        if action == "remove":
            worktrees.remove(registry, task, yes=True, force=True)
        else:
            worktrees.forget(registry, task, yes=True)

    with session_lock(registry.root, task["id"]) as record:
        with pytest.raises(ManagementError) as active:
            retire()
        assert active.value.code == "worker_active"
        record.write_text(json.dumps({"state": "running"}))
    with pytest.raises(ManagementError) as unknown:
        retire()
    assert unknown.value.code == "worker_unknown"
    assert Path(task["path"]).is_dir()
    assert registry.get("taskenv", task["id"]) == task
    record.write_text(json.dumps({"state": "exited"}))
    retire()
