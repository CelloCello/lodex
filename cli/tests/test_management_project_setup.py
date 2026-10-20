from __future__ import annotations

import json
from pathlib import Path

import pytest

from lodex_cli import main as cli
from lodex_core.management import project_config, worktrees
from lodex_core.management.store import Registry


def test_project_display_name_uses_fixed_cli_id(
    registry: Registry,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LODEX_HOME", str(registry.root))
    assert (
        cli.main(
            ["project", "add", "stable-id", str(repo), "--display-name", "First name", "--json"]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["result"]["display_name"] == "First name"
    assert cli.main(["project", "rename", "stable-id", "新的名稱", "--json"]) == 0
    renamed = json.loads(capsys.readouterr().out)["result"]
    assert renamed["id"] == "stable-id" and renamed["display_name"] == "新的名稱"
    assert cli.main(["project", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == [renamed]
    assert cli.main(["project", "add", "another-id", str(repo), "--json"]) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "already_registered"
    assert error["details"] == {"existing_project": "stable-id"}
    assert "新的名稱" in error["message"]
    assert cli.main(["project", "pin", "stable-id", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["pinned"] is True
    assert cli.main(["project", "pin", "stable-id", "--unpin", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["pinned"] is False
    assert cli.main(["project", "delete", "stable-id", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["removed"] is False
    assert registry.get("project", "stable-id")["display_name"] == "新的名稱"
    assert cli.main(["project", "delete", "stable-id", "--yes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["removed"] is True
    assert repo.exists() and registry.all("project") == []


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
