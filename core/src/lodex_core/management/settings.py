"""Port assignments, resolved environment inspection and safe dotenv export."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from lodex_core.management.common import ManagementError
from lodex_core.management.environment import SecretProvider, inputs
from lodex_core.management.project_config import CONFIG, load
from lodex_core.management.store import Registry
from lodex_core.management.worktrees import allocate, git, require_present


def set_port(registry: Registry, task: dict[str, Any], key: str, value: str) -> dict[str, Any]:
    with registry.lock(task["id"]):
        registry.reload_task(task)
        config = load(require_present(task) / CONFIG)
        if key not in config["ports"]:
            raise ManagementError("unknown_setting", f"No configured ports.{key}")
        try:
            port = int(value)
        except ValueError as exc:
            raise ManagementError("invalid_port", "Port must be an integer") from exc
        if not 1 <= port <= 65535:
            raise ManagementError("invalid_port", "Port must be 1-65535")
        with registry.lock("registry"):
            task["ports"].pop(key, None)
            config["ports"][key] = port
            allocate(registry, task, config)
            registry.put("taskenv", task)
        return {"id": task["id"], "section": "ports", "key": key, "updated": True}


def show(registry: Registry, task: dict[str, Any]) -> dict[str, Any]:
    config, values, _ = inputs(registry, task, secrets=False, persist=False)
    return {"values": values, "secret_refs": config["secrets"]}


def export(
    registry: Registry, task: dict[str, Any], relative: str, provider: SecretProvider | None = None
) -> dict[str, Any]:
    with registry.lock(task["id"]):
        registry.reload_task(task)
        root = require_present(task)
        path = root / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts or path.is_symlink():
            raise ManagementError(
                "invalid_output", "Output must be a regular file inside the checkout"
            )
        if not path.parent.is_dir() or root not in path.resolve().parents:
            raise ManagementError("invalid_output", "Output parent must exist inside the checkout")
        _config, values, known = inputs(registry, task, provider)
        if git(root, "ls-files", "--", relative):
            raise ManagementError(
                "tracked_env", "Refusing to write configuration to a Git-tracked file"
            )
        if known:
            try:
                git(root, "check-ignore", "--", relative)
            except ManagementError as exc:
                raise ManagementError(
                    "unignored_secret_file",
                    "Add output to repo ignore rules before exporting secrets",
                ) from exc
        exports = task.setdefault("exports", {})
        if path.exists():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if exports.get(relative) != digest:
                raise ManagementError(
                    "unmanaged_env", "Output is handwritten or modified; choose another path"
                )
        content = "".join(
            f"{key}={json.dumps(value, ensure_ascii=False)}\n"
            for key, value in sorted(values.items())
        )
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".lodex-env-")
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(content)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        exports[relative] = hashlib.sha256(content.encode()).hexdigest()
        registry.put("taskenv", task)
        return {"path": str(path), "mode": "0600", "keys": sorted(values)}
