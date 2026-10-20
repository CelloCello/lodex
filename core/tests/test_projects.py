from __future__ import annotations

import subprocess
from pathlib import Path

from lodex_core.history.projects import project_identity


def test_git_remote_identity_is_stable_across_directories(tmp_path: Path) -> None:
    repositories = (tmp_path / "first", tmp_path / "second")
    for repository in repositories:
        repository.mkdir()
        subprocess.run(["git", "init", "-q", str(repository)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "config",
                "remote.origin.url",
                "git@GitHub.com:Owner/Lodex.git",
            ],
            check=True,
        )

    assert project_identity(repositories[0]) == "git:github.com/Owner/Lodex"
    assert project_identity(repositories[1]) == "git:github.com/Owner/Lodex"


def test_non_git_directory_uses_normalized_path(tmp_path: Path) -> None:
    assert project_identity(tmp_path) == f"path:{tmp_path.resolve()}"
