from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import pytest

from lodex_cli import main as cli

SKILL_CASES = [None, "lodex-worktree", "lodex-services", "lodex-project-setup"]


def assert_skill_contents(target: Path, name: str) -> None:
    expected = {Path("SKILL.md")}
    if name == "lodex-history":
        expected.add(Path("agents/openai.yaml"))
    assert {p.relative_to(target) for p in target.rglob("*") if p.is_file()} == expected
    assert f"name: {name}" in (target / "SKILL.md").read_text().splitlines()
    source = files("lodex_cli").joinpath("bundled_skills", name)
    for relative in expected:
        assert (target / relative).read_bytes() == source.joinpath(*relative.parts).read_bytes()


@pytest.mark.parametrize("skill_name", SKILL_CASES)
def test_skill_install_dry_run_install_and_idempotency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    skill_name: str | None,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    invalid_config = tmp_path / "invalid.toml"
    invalid_config.write_text("[embedding]\ndimension = 0\n", encoding="utf-8")
    monkeypatch.setenv("LODEX_CONFIG", str(invalid_config))
    name = skill_name or "lodex-history"
    args = [skill_name] if skill_name else []
    target = tmp_path / ".agents" / "skills" / name

    assert cli.main(["skill", "install", *args, "--dry-run"]) == 0
    assert "Would install" in capsys.readouterr().out
    assert not target.exists()

    assert cli.main(["skill", "install", *args]) == 0
    assert "Installed" in capsys.readouterr().out
    assert_skill_contents(target, name)

    assert cli.main(["skill", "install", *args]) == 0
    assert "already up to date" in capsys.readouterr().out
    assert_skill_contents(target, name)


@pytest.mark.parametrize("skill_name", SKILL_CASES)
def test_skill_install_dry_run_then_updates_different_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    skill_name: str | None,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    name = skill_name or "lodex-history"
    args = [skill_name] if skill_name else []
    target = tmp_path / ".agents" / "skills" / name
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("user content", encoding="utf-8")
    (target / "stale.txt").write_text("stale", encoding="utf-8")

    assert cli.main(["skill", "install", *args, "--dry-run"]) == 0
    assert "Would update" in capsys.readouterr().out
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "user content"

    assert cli.main(["skill", "install", *args]) == 0
    assert "Updated" in capsys.readouterr().out
    assert_skill_contents(target, name)

    assert cli.main(["skill", "install", *args]) == 0
    assert "already up to date" in capsys.readouterr().out


@pytest.mark.parametrize("skill_name", SKILL_CASES)
def test_skill_remove_dry_run_and_missing_installation_are_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    skill_name: str | None,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    name = skill_name or "lodex-history"
    args = [skill_name] if skill_name else []
    target = tmp_path / ".agents" / "skills" / name
    other = tmp_path / ".agents" / "skills" / "unrelated"
    other.mkdir(parents=True)
    (other / "SKILL.md").write_text("unrelated skill")
    assert cli.main(["skill", "install", *args]) == 0
    capsys.readouterr()

    assert cli.main(["skill", "remove", *args, "--dry-run"]) == 0
    assert "Would remove" in capsys.readouterr().out
    assert_skill_contents(target, name)

    assert cli.main(["skill", "remove", *args]) == 0
    assert "Removed" in capsys.readouterr().out
    assert not target.exists()

    assert cli.main(["skill", "remove", *args]) == 0
    assert "not installed" in capsys.readouterr().out
    assert (other / "SKILL.md").read_text() == "unrelated skill"


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
