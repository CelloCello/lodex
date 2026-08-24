"""Stable project identities shared by indexing and search filters."""

from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import urlparse


def _normalize_remote(remote: str) -> str:
    value = remote.strip().removesuffix(".git").rstrip("/")
    if value.startswith("git@") and ":" in value:
        host, path = value[4:].split(":", maxsplit=1)
        return f"git:{host.lower()}/{path}"
    if "://" in value:
        parsed = urlparse(value)
        host = parsed.hostname.lower() if parsed.hostname else ""
        port = f":{parsed.port}" if parsed.port else ""
        path = parsed.path.lstrip("/")
        return f"git:{host}{port}/{path}"
    return f"git:{value}"


def project_identity(value: str | Path) -> str:
    """Prefer a Git remote identity; fall back to a normalized absolute path."""

    path = Path(value).expanduser().resolve()
    if path.exists():
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "config", "--get", "remote.origin.url"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and result.returncode == 0 and result.stdout.strip():
            return _normalize_remote(result.stdout)
    return f"path:{path}"
