from __future__ import annotations

import errno
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from lodex_core.management import service_runtime
from lodex_core.management.common import ManagementError, write_private


@pytest.fixture
def observation(tmp_path: Path) -> dict[str, Any]:
    root = tmp_path / "runtime"
    launch = "a" * 32
    directory = root / "runs" / launch
    directory.mkdir(parents=True)
    write_private(
        directory / "status.json",
        json.dumps({"state": "starting", "exit_code": None, "observed_at": "2026-11-09T00:00:00Z"}),
    )
    write_private(directory / "output.log", "old log\n")
    info = root.stat()
    return {
        "directory": str(directory),
        "delegated": {"root": str(root), "launch": launch, "inode": [info.st_dev, info.st_ino]},
    }


@pytest.mark.parametrize("filename", ["status.json", "output.log"])
def test_atomic_replace_after_open_reopens_the_observation(
    observation: dict[str, Any], monkeypatch: pytest.MonkeyPatch, filename: str
) -> None:
    path = Path(observation["directory"]) / filename
    newest = {"state": "running", "exit_code": None, "observed_at": "2026-11-09T00:00:01Z"}
    content = json.dumps(newest) if filename == "status.json" else "new log\n"
    fstat = os.fstat
    unlinked: list[int] = []
    descriptors: list[int] = []

    def replace_before_stat(fd: int) -> os.stat_result:
        info = fstat(fd)
        if stat.S_ISREG(info.st_mode):
            descriptors.append(fd)
            if not unlinked:
                write_private(path, content)
                info = fstat(fd)
                unlinked.append(info.st_nlink)
        return info

    monkeypatch.setattr(os, "fstat", replace_before_stat)
    if filename == "status.json":
        assert service_runtime.status(observation) == newest
    else:
        assert service_runtime.owned_bytes(observation, filename, tail=True).decode() == content
    assert unlinked == [0] and len(descriptors) == 2
    for fd in descriptors:
        with pytest.raises(OSError) as closed:
            fstat(fd)
        assert closed.value.errno == errno.EBADF


@pytest.mark.parametrize("replacements", [2, 3])
def test_atomic_replacements_have_a_bounded_retry_budget(
    observation: dict[str, Any], monkeypatch: pytest.MonkeyPatch, replacements: int
) -> None:
    path = Path(observation["directory"]) / "output.log"
    fstat = os.fstat
    reads = 0

    def replace_before_stat(fd: int) -> os.stat_result:
        nonlocal reads
        info = fstat(fd)
        if stat.S_ISREG(info.st_mode):
            reads += 1
            assert reads <= 3, "Observation retry must be bounded"
            if reads <= replacements:
                write_private(path, f"replacement {reads}\n")
                info = fstat(fd)
        return info

    monkeypatch.setattr(os, "fstat", replace_before_stat)
    if replacements == 2:
        assert service_runtime.owned_bytes(observation, "output.log") == b"replacement 2\n"
    else:
        with pytest.raises(ManagementError) as unstable:
            service_runtime.owned_bytes(observation, "output.log")
        assert unstable.value.code == "invalid_service_record"
    assert reads == 3


@pytest.mark.parametrize("attack", ["symlink", "hardlink", "fifo"])
def test_retry_rejects_unsafe_replacement_files(
    observation: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    path = Path(observation["directory"]) / "output.log"
    outside = tmp_path / "outside"
    outside.write_text("outside private fixture")
    fstat = os.fstat
    replaced = False

    def replace_before_stat(fd: int) -> os.stat_result:
        nonlocal replaced
        info = fstat(fd)
        if stat.S_ISREG(info.st_mode) and not replaced:
            replaced = True
            path.unlink()
            if attack == "symlink":
                path.symlink_to(outside)
            elif attack == "hardlink":
                path.hardlink_to(outside)
            else:
                os.mkfifo(path)
            info = fstat(fd)
        return info

    monkeypatch.setattr(os, "fstat", replace_before_stat)
    with pytest.raises((OSError, ManagementError)):
        service_runtime.owned_bytes(observation, "output.log")
    assert replaced and outside.read_text() == "outside private fixture"


def test_retry_stays_in_the_pinned_directory_after_a_parent_swap(
    observation: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = Path(observation["directory"])
    moved = directory.with_name("retained")
    outside = tmp_path / "other-task"
    outside.mkdir()
    (outside / "output.log").write_text("outside private fixture")
    fstat = os.fstat
    replaced = False

    def swap_parent_before_stat(fd: int) -> os.stat_result:
        nonlocal replaced
        info = fstat(fd)
        if stat.S_ISREG(info.st_mode) and not replaced:
            replaced = True
            (directory / "output.log").unlink()
            directory.rename(moved)
            directory.symlink_to(outside, target_is_directory=True)
            write_private(moved / "output.log", "safe replacement\n")
            info = fstat(fd)
        return info

    monkeypatch.setattr(os, "fstat", swap_parent_before_stat)
    assert service_runtime.owned_bytes(observation, "output.log") == b"safe replacement\n"
    assert replaced
