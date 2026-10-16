"""Install, update, and remove bundled Lodex skills and their resources."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from shutil import rmtree
from tempfile import TemporaryDirectory

SKILL_NAME = "lodex-history"
SKILL_NAMES = (SKILL_NAME, "lodex-worktree", "lodex-services", "lodex-project-setup", "lodex-herdr")


@dataclass(frozen=True, slots=True)
class SkillInstallResult:
    """Observable result of one skill installation attempt."""

    path: Path
    state: str


def _bundled_files(skill_name: str) -> dict[Path, bytes]:
    if skill_name not in SKILL_NAMES:
        raise ValueError(f"Unknown bundled skill: {skill_name}")
    root = files("lodex_cli").joinpath("bundled_skills", skill_name)
    contents: dict[Path, bytes] = {}

    def collect(directory: Traversable, prefix: Path) -> None:
        for child in directory.iterdir():
            relative = prefix / child.name
            if child.is_dir():
                collect(child, relative)
            elif child.is_file():
                contents[relative] = child.read_bytes()

    collect(root, Path())
    return contents


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


def install_skill(*, dry_run: bool = False, skill_name: str = SKILL_NAME) -> SkillInstallResult:
    """Install or update the bundled skill under the user's agent skill directory."""

    expected = _bundled_files(skill_name)
    target = Path.home() / ".agents" / "skills" / skill_name
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


def remove_skill(*, dry_run: bool = False, skill_name: str = SKILL_NAME) -> SkillInstallResult:
    """Remove the installed skill without following symbolic links."""

    if skill_name not in SKILL_NAMES:
        raise ValueError(f"Unknown bundled skill: {skill_name}")
    target = Path.home() / ".agents" / "skills" / skill_name
    if not _target_exists(target):
        return SkillInstallResult(path=target, state="not-installed")
    if dry_run:
        return SkillInstallResult(path=target, state="would-remove")

    if target.is_symlink() or target.is_file():
        target.unlink()
    else:
        rmtree(target)
    return SkillInstallResult(path=target, state="removed")
