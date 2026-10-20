from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from lodex_core.management import project_config, worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.store import Registry


def test_pin_and_delete_only_empty_project_registrations(registry: Registry, repo: Path) -> None:
    original = worktrees.project_add(registry, "fixture", repo, None, project_name="Project")
    files = {
        path.relative_to(repo): path.read_bytes() for path in repo.rglob("*") if path.is_file()
    }
    pinned = worktrees.project_pin(registry, "fixture", pinned=True)
    assert pinned["pinned"] is True
    assert pinned["source"] == original["source"]
    assert worktrees.project_pin(registry, "fixture", pinned=False)["pinned"] is False
    preview = worktrees.project_delete(registry, "fixture", yes=False)
    assert preview["project"] == "fixture" and not preview["removed"]
    assert registry.get("project", "fixture")["display_name"] == "Project"
    task = worktrees.attach(registry, "fixture", repo)
    for execute in [False, True]:
        with pytest.raises(ManagementError) as blocked:
            worktrees.project_delete(registry, "fixture", yes=execute)
        assert blocked.value.code == "project_not_empty"
    assert registry.get("taskenv", task["id"]) == task
    worktrees.forget(registry, task, yes=True)
    with registry.lock("registry"), pytest.raises(ManagementError) as busy:
        worktrees.project_delete(registry, "fixture", yes=True)
    assert busy.value.code == "busy"
    assert worktrees.project_delete(registry, "fixture", yes=True)["removed"] is True
    assert registry.all("project") == []
    assert {
        path.relative_to(repo): path.read_bytes() for path in repo.rglob("*") if path.is_file()
    } == files


def test_create_checks_project_after_acquiring_registry_lock(
    registry: Registry, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktrees.project_add(registry, "fixture", repo, None)
    original_lock = registry.lock

    @contextmanager
    def delete_before_lock(key: str) -> Iterator[None]:
        if key.startswith("project-"):
            worktrees.project_delete(registry, "fixture", yes=True)
        with original_lock(key):
            yield

    monkeypatch.setattr(registry, "lock", delete_before_lock)
    with pytest.raises(ManagementError) as deleted:
        worktrees.create(registry, "fixture", "HEAD", "must-not-exist")
    assert deleted.value.code == "not_found"
    assert registry.all("taskenv") == []
    assert worktrees.git(repo, "branch", "--list", "must-not-exist") == ""
    assert not (registry.root / "projects").exists()


def test_project_add_copies_source_and_uses_local_recipe(registry: Registry, repo: Path) -> None:
    config = repo / project_config.CONFIG
    config.unlink()
    source = repo.parent / "external.toml"
    original = 'schema_version=1\n[env]\nMODE="source"\n'
    source.write_text(original)
    project = worktrees.project_add(registry, "fixture", repo, source)
    assert project["configuration"] == {
        "method": "copied",
        "path": str(config),
        "source": str(source),
    }
    assert project["source"] == str(config)
    assert config.read_text() == original
    config.write_text(original.replace("source", "local"))
    assert source.read_text() == original
    source.unlink()
    tree = worktrees.create(registry, "fixture", "HEAD", "local-source")
    assert (Path(tree["path"]) / project_config.CONFIG).read_text() == config.read_text()


def test_display_name_preserves_legacy_identity_and_repeated_registration(
    registry: Registry, repo: Path
) -> None:
    original = worktrees.project_add(registry, "fixture", repo, None)
    assert "display_name" not in original
    task = worktrees.attach(registry, "fixture", repo)
    renamed = worktrees.project_update(registry, "fixture", "  中文 Project  ")
    assert renamed["display_name"] == "中文 Project"
    assert {key: value for key, value in renamed.items() if key != "display_name"} == {
        key: value for key, value in original.items() if key != "configuration"
    }
    assert registry.get("taskenv", task["id"]) == task
    reader = Registry(registry.root, read_only=True)
    try:
        assert reader.get("project", "fixture") == renamed
    finally:
        reader.close()
    repeated = worktrees.project_add(registry, "fixture", repo, None, project_name="Ignored")
    assert repeated["already_registered"] is True
    assert repeated["display_name"] == "中文 Project"
    created = worktrees.create(registry, "fixture", "HEAD", "after-rename")
    assert created["project"] == "fixture"
    assert Path(created["path"]).parent == registry.root / "projects" / "fixture"
    with pytest.raises(ManagementError) as duplicate:
        worktrees.project_add(registry, "other-id", repo, None)
    assert duplicate.value.details == {"existing_project": "fixture"}
    assert "中文 Project" in str(duplicate.value)


@pytest.mark.parametrize(
    "invalid", ["", "   ", "bad\nname", "bad\x00name", "bad\x85name", "x" * 121]
)
def test_invalid_display_name_does_not_change_registration(
    registry: Registry, repo: Path, invalid: str
) -> None:
    worktrees.project_add(registry, "fixture", repo, None, project_name="Original")
    before = registry.get("project", "fixture")
    with pytest.raises(ManagementError) as rejected:
        worktrees.project_update(registry, "fixture", invalid)
    assert rejected.value.code == "invalid_name"
    assert registry.get("project", "fixture") == before


def test_name_update_respects_registry_lock(registry: Registry, repo: Path) -> None:
    worktrees.project_add(registry, "fixture", repo, None)
    with registry.lock("registry"), pytest.raises(ManagementError) as busy:
        worktrees.project_update(registry, "fixture", "Updated")
    assert busy.value.code == "busy"
    assert "display_name" not in registry.get("project", "fixture")


@pytest.mark.parametrize("invalid", [False, True])
def test_project_add_keeps_existing_even_with_explicit_source(
    registry: Registry, repo: Path, invalid: bool
) -> None:
    config = repo / project_config.CONFIG
    original = "broken = [" if invalid else 'schema_version=1\n[env]\nMODE="kept"\n'
    config.write_text(original)
    source = repo.parent / "unused-missing.toml"
    if invalid:
        with pytest.raises(ManagementError, match="valid TOML"):
            worktrees.project_add(registry, "fixture", repo, source)
        assert registry.all("project") == []
    else:
        result = worktrees.project_add(registry, "fixture", repo, source)
        assert result["configuration"]["method"] == "existing"
        config.write_text("broken = [")
        with pytest.raises(ManagementError, match="valid TOML"):
            worktrees.project_add(registry, "fixture", repo, None)
        assert len(registry.all("project")) == 1
        original = "broken = ["
    assert config.read_text() == original


@pytest.mark.parametrize("missing", [False, True])
def test_project_add_bad_source_does_not_initialize(
    registry: Registry, repo: Path, missing: bool
) -> None:
    config = repo / project_config.CONFIG
    config.unlink()
    source = repo.parent / "invalid.toml"
    if not missing:
        source.write_text("schema_version=99\n")
    with pytest.raises(ManagementError):
        worktrees.project_add(registry, "fixture", repo, source)
    assert not config.exists()
    assert registry.all("project") == []


def test_project_add_checks_conflicts_and_lock_before_writing(
    registry: Registry, repo: Path
) -> None:
    worktrees.project_add(registry, "fixture", repo, None)
    config = repo / project_config.CONFIG
    config.unlink()
    with pytest.raises(ManagementError) as conflict:
        worktrees.project_add(registry, "different-name", repo, None)
    assert conflict.value.code == "already_registered"
    assert not config.exists()
    with registry.lock("registry"), pytest.raises(ManagementError, match="holds registry"):
        worktrees.project_add(registry, "fixture", repo, None)
    assert not config.exists()
    assert len(registry.all("project")) == 1


def test_project_add_refuses_initialization_outside_checkout(
    registry: Registry, repo: Path
) -> None:
    config = repo / project_config.CONFIG
    config.unlink()
    config.parent.rmdir()
    outside = repo.parent / "outside"
    outside.mkdir()
    config.parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ManagementError, match="inside the worktree"):
        worktrees.project_add(registry, "fixture", repo, None)
    assert list(outside.iterdir()) == []
    assert registry.all("project") == []
