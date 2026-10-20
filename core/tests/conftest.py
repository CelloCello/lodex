from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from lodex_core.management import worktrees
from lodex_core.management.project_config import CONFIG
from lodex_core.management.store import Registry


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    worktrees.git(path, "init", "-q")
    worktrees.git(path, "config", "user.email", "fixture@example.invalid")
    worktrees.git(path, "config", "user.name", "Fixture")
    (path / "README.md").write_text("fixture\n")
    worktrees.git(path, "add", "README.md")
    worktrees.git(path, "commit", "-qm", "initial")
    worktrees.git(path, "tag", "initial")
    (path / ".lodex").mkdir()
    (path / CONFIG).write_text("schema_version = 1\n[ports]\nPORT = 0\n")
    return path


@pytest.fixture
def registry(tmp_path: Path) -> Iterator[Registry]:
    registry = Registry(tmp_path / "manager")
    yield registry
    registry.close()
