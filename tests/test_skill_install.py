from __future__ import annotations

from pathlib import Path

import pytest

from lodex import cli


def test_skill_install_dry_run_install_and_idempotency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    invalid_config = tmp_path / "invalid.toml"
    invalid_config.write_text("[embedding]\ndimension = 0\n", encoding="utf-8")
    monkeypatch.setenv("LODEX_CONFIG", str(invalid_config))
    target = tmp_path / ".agents" / "skills" / "lodex-history"

    assert cli.main(["skill", "install", "--dry-run"]) == 0
    assert "Would install" in capsys.readouterr().out
    assert not target.exists()

    assert cli.main(["skill", "install"]) == 0
    assert "Installed" in capsys.readouterr().out
    assert (target / "SKILL.md").is_file()
    assert (target / "agents" / "openai.yaml").is_file()

    assert cli.main(["skill", "install"]) == 0
    assert "already up to date" in capsys.readouterr().out


def test_skill_install_dry_run_then_updates_different_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".agents" / "skills" / "lodex-history"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("user content", encoding="utf-8")
    (target / "stale.txt").write_text("stale", encoding="utf-8")

    assert cli.main(["skill", "install", "--dry-run"]) == 0
    assert "Would update" in capsys.readouterr().out
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "user content"

    assert cli.main(["skill", "install"]) == 0
    assert "Updated" in capsys.readouterr().out
    assert (target / "SKILL.md").read_text(encoding="utf-8").startswith("---\nname: lodex-history")
    assert not (target / "stale.txt").exists()

    assert cli.main(["skill", "install"]) == 0
    assert "already up to date" in capsys.readouterr().out


def test_skill_remove_dry_run_and_missing_installation_are_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".agents" / "skills" / "lodex-history"
    assert cli.main(["skill", "install"]) == 0
    capsys.readouterr()

    assert cli.main(["skill", "remove", "--dry-run"]) == 0
    assert "Would remove" in capsys.readouterr().out
    assert target.is_dir()

    assert cli.main(["skill", "remove"]) == 0
    assert "Removed" in capsys.readouterr().out
    assert not target.exists()

    assert cli.main(["skill", "remove"]) == 0
    assert "not installed" in capsys.readouterr().out


def test_skill_remove_unlinks_symlink_without_removing_its_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    source = tmp_path / "source-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("source", encoding="utf-8")
    target = tmp_path / ".agents" / "skills" / "lodex-history"
    target.parent.mkdir(parents=True)
    target.symlink_to(source, target_is_directory=True)

    assert cli.main(["skill", "remove"]) == 0
    assert not target.exists()
    assert (source / "SKILL.md").read_text(encoding="utf-8") == "source"


def test_skill_install_replaces_symlink_without_modifying_its_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    source = tmp_path / "source-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("source", encoding="utf-8")
    target = tmp_path / ".agents" / "skills" / "lodex-history"
    target.parent.mkdir(parents=True)
    target.symlink_to(source, target_is_directory=True)

    assert cli.main(["skill", "install"]) == 0
    assert target.is_dir()
    assert not target.is_symlink()
    assert (source / "SKILL.md").read_text(encoding="utf-8") == "source"
