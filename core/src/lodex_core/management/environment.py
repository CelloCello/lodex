"""Explicit environment inputs, saved allocations and secret-aware output."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Protocol

from lodex_core.management.common import ManagementError
from lodex_core.management.project_config import CONFIG, load
from lodex_core.management.store import Registry
from lodex_core.management.worktrees import allocate, require_present


class SecretProvider(Protocol):
    def get(self, reference: str) -> str: ...


def redact(text: str, secrets: list[str]) -> str:
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def expand(value: str, values: dict[str, str]) -> str:
    def replacement(match: re.Match[str]) -> str:
        key = match[1]
        if key not in values:
            raise ManagementError("missing_value", f"Unknown environment placeholder: {key}")
        return values[key]

    return re.sub(r"\$\{([A-Z_][A-Z0-9_]*)\}", replacement, value)


def inputs(
    registry: Registry,
    task: dict[str, Any],
    provider: SecretProvider | None = None,
    *,
    secrets: bool = True,
    persist: bool = True,
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    root = require_present(task)
    config = load(root / CONFIG)
    if persist:
        with registry.lock("registry"):
            allocate(registry, task, config)
            registry.put("taskenv", task)
    values = {
        "LODEX_TASKENV_ID": task["id"],
        "LODEX_PROJECT": task["project"],
        "LODEX_WORKTREE": str(root),
    }
    values.update({k: str(v) for k, v in task["ports"].items() if k in config["ports"]})
    # Values may use saved identifiers/ports; no recursive dependency engine.
    for key, value in config["env"].items():
        values[key] = expand(value, values)
    known: list[str] = []
    if secrets and config["secrets"]:
        if provider is None:
            from lodex_core.management.secrets import SQLiteSecrets

            provider = SQLiteSecrets(registry)
        for key, reference in config["secrets"].items():
            value = provider.get(reference)
            if not value or "\x00" in value:
                raise ManagementError("missing_secret", f"Missing usable secret: {key}")
            known.append(value)
            values[key] = value
    return config, values, known


def process_env(values: dict[str, str]) -> dict[str, str]:
    # Do not implicitly copy the caller's project credentials into another taskenv.
    inherited = {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT"}
    }
    return {**inherited, **values}


def command_argv(spec: dict[str, Any], values: dict[str, str], known: list[str]) -> list[str]:
    argv = [expand(arg, values) for arg in spec["argv"]]
    if any(secret in arg for secret in known for arg in argv):
        raise ManagementError("secret_in_argv", "Pass secrets through process env, never argv")
    return argv


def log_tail(path: Path, limit: int = 65536) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - limit))
        return stream.read(limit).decode("utf-8", errors="replace")


class LogRedactor:
    """Keep a bounded suffix so secrets split across pipe reads are still hidden."""

    def __init__(self, secrets: list[str]) -> None:
        self.secrets = [s.encode() for s in secrets if s]
        self.pending = b""
        self.width = max((len(s) for s in self.secrets), default=1)

    def feed(self, data: bytes, *, final: bool = False) -> bytes:
        self.pending += data
        output = bytearray()
        while self.pending and (final or len(self.pending) >= self.width):
            match = next(
                (
                    s
                    for s in sorted(self.secrets, key=len, reverse=True)
                    if self.pending.startswith(s)
                ),
                None,
            )
            if match:
                output.extend(b"[REDACTED]")
                self.pending = self.pending[len(match) :]
            else:
                output.append(self.pending[0])
                self.pending = self.pending[1:]
        return bytes(output)
