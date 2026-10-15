from __future__ import annotations

from pathlib import Path

import pytest

from lodex_core.management import project_config, worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.store import Registry


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
