from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from lodex_core.management import project_config, worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.store import Registry


@pytest.fixture(autouse=True)
def project(registry: Registry, repo: Path) -> None:
    (repo / project_config.CONFIG).write_text("schema_version=1\n")
    worktrees.git(repo, "add", str(project_config.CONFIG))
    worktrees.git(repo, "commit", "-qm", "Add configuration")
    worktrees.project_add(registry, "sample", repo, None)


@pytest.mark.parametrize(
    ("branch", "slug"),
    [
        ("demo/change-title", "demo-change-title"),
        ("Feature/Login", "feature-login"),
        ("release/v1.2_3", "release-v1-2-3"),
        ("feature/a---b", "feature-a-b"),
        ("修正/登入", "worktree"),
        ("___", "worktree"),
    ],
)
def test_readable_directory_keeps_full_id_and_original_branch(
    registry: Registry, branch: str, slug: str
) -> None:
    task = worktrees.create(registry, "sample", "HEAD", branch)
    path = Path(task["path"])
    assert len(task["id"]) == 16
    assert path == registry.root / "projects" / "sample" / f"{slug}--{task['id'][:8]}"
    assert worktrees.inspect(registry, task)["branch"] == branch
    assert worktrees.resolve(registry, str(path / ".lodex"))["id"] == task["id"]
    assert worktrees.resolve(registry, task["id"])["path"] == str(path)


def test_long_branch_stays_within_directory_limit(registry: Registry) -> None:
    branch = "feature/" + "long-" * 30 + "end"
    task = worktrees.create(registry, "sample", "HEAD", branch)
    slug, suffix = Path(task["path"]).name.rsplit("--", 1)
    assert slug.startswith("feature-long-") and len(slug) <= 64 and not slug.endswith("-")
    assert suffix == task["id"][:8]
    assert worktrees.inspect(registry, task)["branch"] == branch


@pytest.mark.parametrize("removed", [False, True])
def test_normalized_name_and_short_id_collision_preserves_existing_record(
    registry: Registry, monkeypatch: pytest.MonkeyPatch, removed: bool
) -> None:
    ids = iter([uuid.UUID("a" * 32), uuid.UUID("a" * 8 + "b" * 24), uuid.UUID("c" * 32)])
    monkeypatch.setattr(uuid, "uuid4", lambda: next(ids))
    first = worktrees.create(registry, "sample", "HEAD", "feature/login")
    if removed:
        worktrees.remove(registry, first, yes=True, force=False)
    saved = registry.get("taskenv", first["id"])
    second = worktrees.create(registry, "sample", "HEAD", "feature-login")
    assert Path(second["path"]).name == "feature-login--cccccccc"
    assert registry.get("taskenv", first["id"]) == saved
    assert Path(first["path"]).exists() is not removed
    assert len(registry.all("taskenv")) == 2


def test_full_id_collision_with_different_slug_does_not_overwrite_task(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = iter([uuid.UUID("a" * 32), uuid.UUID("a" * 32), uuid.UUID("b" * 32)])
    monkeypatch.setattr(uuid, "uuid4", lambda: next(ids))
    first = worktrees.create(registry, "sample", "HEAD", "first")
    second = worktrees.create(registry, "sample", "HEAD", "second")
    assert first["id"] != second["id"]
    assert registry.get("taskenv", first["id"]) == first
    assert Path(first["path"]).is_dir()


@pytest.mark.parametrize("occupied", ["directory", "file", "symlink"])
def test_existing_filesystem_entry_is_not_reused(
    registry: Registry, monkeypatch: pytest.MonkeyPatch, occupied: str
) -> None:
    path = registry.root / "projects" / "sample" / "feature-login--aaaaaaaa"
    path.parent.mkdir(parents=True)
    if occupied == "directory":
        path.mkdir()
    elif occupied == "file":
        path.write_text("preserve me")
    else:
        path.symlink_to(path.parent / "missing")
    ids = iter([uuid.UUID("a" * 32), uuid.UUID("b" * 32)])
    monkeypatch.setattr(uuid, "uuid4", lambda: next(ids))
    task = worktrees.create(registry, "sample", "HEAD", "feature/login")
    assert Path(task["path"]).name == "feature-login--bbbbbbbb"
    if occupied == "directory":
        assert list(path.iterdir()) == []
    elif occupied == "file":
        assert path.read_text() == "preserve me"
    else:
        assert path.is_symlink() and not path.exists()


def test_repeated_collision_fails_before_creating_a_branch(
    registry: Registry, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID("a" * 32))
    first = worktrees.create(registry, "sample", "HEAD", "first")
    branches = worktrees.git(repo, "branch", "--list")
    with pytest.raises(ManagementError, match="unique worktree") as error:
        worktrees.create(registry, "sample", "HEAD", "second")
    assert error.value.code == "path_conflict"
    assert worktrees.git(repo, "branch", "--list") == branches
    assert registry.all("taskenv") == [first]


def test_legacy_path_and_branch_changes_do_not_move_checkouts(
    registry: Registry, repo: Path
) -> None:
    legacy_id = "0123456789abcdef"
    legacy_path = registry.root / "projects" / "sample" / legacy_id
    worktrees.git(repo, "worktree", "add", "-b", "legacy", str(legacy_path), "HEAD")
    legacy = worktrees.attach(registry, "sample", legacy_path, owned=True, task_id=legacy_id)
    current = worktrees.create(registry, "sample", "HEAD", "feature/new")
    for task in (legacy, current):
        path = Path(task["path"])
        before = path.stat().st_ino
        worktrees.git(path, "branch", "-m", f"renamed-{task['id']}")
        worktrees.git(path, "checkout", "--detach")
        with_registry = Registry(registry.root)
        try:
            assert worktrees.attach(with_registry, "sample", path) == task
            assert worktrees.resolve(with_registry, str(path))["id"] == task["id"]
            assert worktrees.inspect(with_registry, task)["branch"] is None
        finally:
            with_registry.close()
        assert path.stat().st_ino == before
        worktrees.remove(registry, task, yes=True, force=False)
        assert not path.exists()
        worktrees.forget(registry, task, yes=True)
    assert registry.all("taskenv") == []


@pytest.mark.parametrize("branch", ["../escape", "feature//invalid"])
def test_slug_does_not_make_invalid_git_branch_valid(
    registry: Registry, repo: Path, branch: str
) -> None:
    branches = worktrees.git(repo, "branch", "--list")
    with pytest.raises(ManagementError):
        worktrees.create(registry, "sample", "HEAD", branch)
    assert registry.all("taskenv") == []
    assert worktrees.git(repo, "branch", "--list") == branches
