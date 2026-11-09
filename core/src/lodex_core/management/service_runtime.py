"""Read worker-owned observations without following worker-controlled paths."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from lodex_core.management.common import ManagementError, read_json

STATES = {"starting", "running", "stopping", "stopped", "exited", "failed", "unknown"}
TERMINAL_STATES = {"stopped", "exited", "failed"}


@contextmanager
def runtime_root(owner: dict[str, Any]) -> Iterator[int]:
    descriptor = os.open(owner["root"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        observed = os.fstat(descriptor)
        if [observed.st_dev, observed.st_ino] != owner["inode"]:
            raise ManagementError("identity_changed", "Delegated runtime directory was replaced")
        yield descriptor
    finally:
        os.close(descriptor)


def owned_bytes(record: dict[str, Any], filename: str, *, tail: bool = False) -> bytes:
    """The root identity and launch ID come from the manager's registry, never RPC."""
    owner = record["delegated"]
    root = Path(owner["root"])
    launch = owner["launch"]
    if (
        len(launch) != 32
        or any(char not in "0123456789abcdef" for char in launch)
        or filename not in {"status.json", "output.log"}
        or Path(record["directory"]) != root / "runs" / launch
    ):
        raise ManagementError("invalid_service_record", "Invalid delegated service location")
    with ExitStack() as stack:
        descriptor = stack.enter_context(runtime_root(owner))
        for part in ("runs", launch):
            descriptor = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            stack.callback(os.close, descriptor)
        directory_fd = descriptor
        for _ in range(3):
            descriptor = os.open(
                filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
            )
            try:
                observed = os.fstat(descriptor)
                if stat.S_ISREG(observed.st_mode) and observed.st_nlink == 0:
                    # Atomic replacement can unlink the opened snapshot before fstat.
                    # Reopen only the filename, retaining the verified directory FDs.
                    continue
                if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
                    raise ManagementError(
                        "invalid_service_record", "Expected a private regular observation"
                    )
                limit = 65536 if tail else 16384
                if tail:
                    os.lseek(descriptor, max(0, observed.st_size - limit), os.SEEK_SET)
                elif observed.st_size > limit:
                    raise ManagementError(
                        "invalid_service_record", "Service observation is too large"
                    )
                return os.read(descriptor, limit)
            finally:
                os.close(descriptor)
        raise ManagementError(
            "invalid_service_record", "Observation kept changing; retry inspection"
        )


def status(record: dict[str, Any]) -> dict[str, Any]:
    if "delegated" not in record:
        return read_json(Path(record["directory"]) / "status.json")
    try:
        raw = json.loads(owned_bytes(record, "status.json"))
    except (ValueError, RecursionError) as exc:
        raise ManagementError("invalid_service_record", "Invalid service observation JSON") from exc
    return parse_status(raw)


def parse_status(raw: Any) -> dict[str, Any]:
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("state"), str)
        or raw.get("state") not in STATES
        or not isinstance(raw.get("observed_at"), str)
        or type(raw.get("exit_code")) not in (int, type(None))
        or ("pid" in raw and (type(raw["pid"]) is not int or raw["pid"] <= 0))
        or ("error" in raw and not isinstance(raw["error"], str))
    ):
        raise ManagementError("invalid_service_record", "Invalid service observation")
    return {
        key: raw[key] for key in ("state", "observed_at", "exit_code", "pid", "error") if key in raw
    }
