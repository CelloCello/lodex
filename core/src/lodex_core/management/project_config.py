"""Version-one worktree-local project configuration."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from lodex_core.management.common import ManagementError, name
from lodex_core.management.secrets import validate_reference

CONFIG = Path(".lodex/project.toml")
SKELETON = """schema_version = 1

# Ordinary environment variables
# [env]
# APP_MODE = "development"

# Environment variable -> stored secret reference
# [secrets]
# API_TOKEN = "secret:app-dev-token"

# Define commands and services for this repository before running them.
"""


def load(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, ValueError) as exc:
        raise ManagementError("config_unavailable", f"Cannot read valid TOML: {path}") from exc
    allowed = {"schema_version", "env", "secrets", "ports", "commands", "services", "tools"}
    if (
        type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or set(data) - allowed
    ):
        raise ManagementError("invalid_config", "Expected schema_version=1 and supported fields")
    for section in allowed - {"schema_version", "tools"}:
        value = data.setdefault(section, {})
        if not isinstance(value, dict):
            raise ManagementError("invalid_config", f"{section} must be a table")
    for section in ("env", "secrets", "ports"):
        for key, value in data[section].items():
            if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key) or key.startswith("LODEX_"):
                raise ManagementError(
                    "invalid_config", f"Invalid or reserved environment name: {key}"
                )
            if section == "ports":
                if type(value) is not int or not 0 <= value <= 65535:
                    raise ManagementError(
                        "invalid_config", "Ports must be 0 (allocated) or 1-65535"
                    )
            elif not isinstance(value, str):
                raise ManagementError("invalid_config", f"{section}.{key} must be a string")
            elif "\x00" in value:
                raise ManagementError("invalid_config", f"{section}.{key} cannot contain NUL")
            elif section == "secrets":
                validate_reference(value)
    keys: set[str] = set()
    for section in ("env", "secrets", "ports"):
        if keys & data[section].keys():
            raise ManagementError("invalid_config", "env, secrets and ports names must be distinct")
        keys.update(data[section])
    tools = data.setdefault("tools", [])
    if not isinstance(tools, list) or any(not isinstance(t, str) or not t for t in tools):
        raise ManagementError("invalid_config", "tools must be an array of executable names")
    for section in ("commands", "services"):
        for key, spec in data[section].items():
            name(key)
            if not isinstance(spec, dict):
                raise ManagementError("invalid_config", f"{section}.{key} must be a table")
            if section == "services" and "external" in spec:
                raise ManagementError(
                    "invalid_config",
                    f"services.{key}.external is no longer supported. "
                    "For an external dependency, remove the service entry and use env/secrets. "
                    "For a managed process, remove external and provide argv.",
                )
            fields = (
                {"argv", "scripts"}
                if section == "commands"
                else {
                    "argv",
                    "scripts",
                    "url",
                    "ready_port",
                    "ready_argv",
                    "ready_timeout",
                    "stop_timeout",
                }
            )
            if set(spec) - fields:
                raise ManagementError("invalid_config", f"Unknown fields in {section}.{key}")
            argv = spec.get("argv")
            if (
                not isinstance(argv, list)
                or not argv
                or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv)
            ):
                raise ManagementError(
                    "invalid_config", f"{section}.{key}.argv needs a string array"
                )
            scripts = spec.get("scripts", [])
            if not isinstance(scripts, list) or any(
                not isinstance(p, str) or Path(p).is_absolute() or ".." in Path(p).parts
                for p in scripts
            ):
                raise ManagementError("invalid_config", "scripts must contain repo-relative paths")
            if "ready_port" in spec and (
                not isinstance(spec["ready_port"], str) or spec["ready_port"] not in data["ports"]
            ):
                raise ManagementError("invalid_config", "ready_port must name a configured port")
            if "ready_argv" in spec:
                probe = spec["ready_argv"]
                if (
                    not isinstance(probe, list)
                    or not probe
                    or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in probe)
                    or "ready_port" in spec
                ):
                    raise ManagementError(
                        "invalid_config",
                        "ready_argv needs a string array and cannot combine with ready_port",
                    )
            stop_timeout = spec.get("stop_timeout", 3)
            if type(stop_timeout) not in (int, float) or not 0 < stop_timeout <= 300:
                raise ManagementError("invalid_config", "stop_timeout must be >0 and <=300")
            timeout = spec.get("ready_timeout", 10)
            if type(timeout) not in (int, float) or not 0 < timeout <= 300:
                raise ManagementError("invalid_config", "ready_timeout must be >0 and <=300")
            if "url" in spec and (
                not isinstance(spec["url"], str)
                or not spec["url"].startswith(("http://", "https://"))
            ):
                raise ManagementError("invalid_config", "url must use http:// or https://")
    return data


def check_command(root: Path, spec: dict[str, Any], config: dict[str, Any]) -> None:
    for tool in config["tools"]:
        if shutil.which(tool) is None:
            raise ManagementError("missing_tool", f"Required executable is unavailable: {tool}")
    for script in spec.get("scripts", []):
        if not (root / script).is_file():
            raise ManagementError("missing_script", f"Missing repo script: {root / script}")


def supply(root: Path, source: Path | None) -> dict[str, str]:
    """Keep existing config; copy a source, or initialize when explicitly passed None."""
    target = root / CONFIG
    if target.exists() or target.is_symlink():
        load(target)
        return {"method": "existing", "path": str(target)}
    if source is not None:
        load(source)
    if root.resolve() not in target.resolve().parents:
        raise ManagementError("invalid_config_path", "Configuration must be inside the worktree")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(source.read_bytes() if source is not None else SKELETON.encode("utf-8"))
        load(Path(temporary))
        # Atomic no-replace publication: parallel callers cannot truncate another copy.
        try:
            os.link(temporary, target)
        except FileExistsError:
            load(target)
            return {"method": "existing", "path": str(target)}
    finally:
        Path(temporary).unlink(missing_ok=True)
    if source is not None:
        return {"method": "copied", "path": str(target), "source": str(source)}
    return {"method": "initialized", "path": str(target)}
