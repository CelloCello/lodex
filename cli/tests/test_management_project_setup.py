from __future__ import annotations

import json
from pathlib import Path

import pytest

from lodex_cli import main as cli
from lodex_core.management import project_config, worktrees
from lodex_core.management.store import Registry


def test_project_add_initializes_reports_and_preserves_edits(
    registry: Registry,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = repo / project_config.CONFIG
    config.unlink()
    config.parent.rmdir()
    monkeypatch.setenv("LODEX_HOME", str(registry.root))
    assert cli.main(["project", "add", "fixture", str(repo), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["configuration"] == {"method": "initialized", "path": str(config)}
    assert str(config) in result["next_step"]
    assert result["source"] == str(config)
    parsed = project_config.load(config)
    assert parsed["env"] == parsed["secrets"] == parsed["commands"] == parsed["services"] == {}
    assert worktrees.git(repo, "ls-files") == "README.md"
    assert registry.all("taskenv") == []

    edited = 'schema_version=1\n[env]\nMODE="edited"\n'
    config.write_text(edited)
    again = worktrees.project_add(registry, "fixture", repo, None)
    assert again["configuration"]["method"] == "existing"
    assert config.read_text() == edited
    assert len(registry.all("project")) == 1
    tree = worktrees.create(registry, "fixture", "HEAD", "from-initialized")
    assert (Path(tree["path"]) / project_config.CONFIG).read_text() == edited
