"""Install, update, and remove the bundled Lodex history skill."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from shutil import rmtree
from tempfile import TemporaryDirectory

SKILL_NAME = "lodex-history"
SKILL_FILES = (Path("SKILL.md"), Path("agents/openai.yaml"))


@dataclass(frozen=True, slots=True)
class SkillInstallResult:
    """Observable result of one skill installation attempt."""

    path: Path
    state: str


def _bundled_files() -> dict[Path, bytes]:
    root = files("lodex").joinpath("bundled_skills", SKILL_NAME)
    return {relative: root.joinpath(*relative.parts).read_bytes() for relative in SKILL_FILES}


def _matches_existing(target: Path, expected: dict[Path, bytes]) -> bool:
    return all(
        (target / relative).is_file() and (target / relative).read_bytes() == content
        for relative, content in expected.items()
    )


def _target_exists(target: Path) -> bool:
    return target.exists() or target.is_symlink()


def _stage_skill(expected: dict[Path, bytes], temporary: Path) -> Path:
    staging = temporary / SKILL_NAME
    for relative, content in expected.items():
        destination = staging / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return staging


def install_skill(*, dry_run: bool = False) -> SkillInstallResult:
    """Install or update the bundled skill under the user's agent skill directory."""

    expected = _bundled_files()
    target = Path.home() / ".agents" / "skills" / SKILL_NAME
    if _target_exists(target):
        if target.is_dir() and _matches_existing(target, expected):
            return SkillInstallResult(path=target, state="unchanged")
        if dry_run:
            return SkillInstallResult(path=target, state="would-update")

        with TemporaryDirectory(prefix=f".{SKILL_NAME}-", dir=target.parent) as temporary:
            temporary_path = Path(temporary)
            staging = _stage_skill(expected, temporary_path)
            previous = temporary_path / "previous"
            target.replace(previous)
            try:
                staging.replace(target)
            except OSError:
                previous.replace(target)
                raise
        return SkillInstallResult(path=target, state="updated")

    if dry_run:
        return SkillInstallResult(path=target, state="would-install")
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{SKILL_NAME}-", dir=target.parent) as temporary:
        staging = _stage_skill(expected, Path(temporary))
        staging.replace(target)
    return SkillInstallResult(path=target, state="installed")


def remove_skill(*, dry_run: bool = False) -> SkillInstallResult:
    """Remove the installed skill without following symbolic links."""

    target = Path.home() / ".agents" / "skills" / SKILL_NAME
    if not _target_exists(target):
        return SkillInstallResult(path=target, state="not-installed")
    if dry_run:
        return SkillInstallResult(path=target, state="would-remove")

    if target.is_symlink() or target.is_file():
        target.unlink()
    else:
        rmtree(target)
    return SkillInstallResult(path=target, state="removed")
