"""Small shared management contracts and private file helpers."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APPLICATION_ID = 0x4C44584D


class ManagementError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def now() -> str:
    return datetime.now(UTC).isoformat()


def name(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", value):
        raise ManagementError("invalid_name", "Use 1-64 letters, digits, underscores or hyphens")
    return value


def private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def write_private(path: Path, data: str) -> None:
    private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".lodex-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ManagementError("invalid_record", f"Cannot read record {path}") from exc
    if not isinstance(value, dict):
        raise ManagementError("invalid_record", f"Expected object in {path}")
    return value
