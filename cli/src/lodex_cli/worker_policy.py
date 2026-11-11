"""Reviewable, per-launch Codex settings; never installs a global profile.

These settings constrain local execution, not arbitrary tools offered by the
agent host. The launched agent still needs an effective-settings/tool check.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import tempfile
import tomllib
import uuid
from pathlib import Path
from typing import Any

from lodex_core.management import worktrees
from lodex_core.management.common import ManagementError, private_dir, read_json, write_private
from lodex_core.management.delegation import KIND, Client
from lodex_core.management.project_config import CONFIG, check_command, digest, load
from lodex_core.management.store import Registry
from lodex_core.management.workspace import runtime_base, validate_checkout


def toml_value(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + "=" + toml_value(v) for k, v in value.items()) + "}"
    return json.dumps(value)


def tool_overrides(root: Path, profile: str, codex_home: Path) -> list[str]:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", profile):
        raise ManagementError("worker_profile", "Use an explicit config profile name")
    selected = codex_home / f"{profile}.config.toml"
    if not selected.is_file():
        raise ManagementError(
            "worker_profile", f"Review and create the worker profile first: {selected}"
        )
    paths = [codex_home / "config.toml", selected]
    paths.extend(parent / ".codex/config.toml" for parent in (*reversed(root.parents), root))
    ids: dict[str, set[str]] = {"mcp_servers": set(), "plugins": set(), "apps": {"_default"}}
    for path in paths:
        if not path.is_file():
            continue
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise ManagementError(
                "worker_profile", f"Cannot inspect Codex settings: {path}"
            ) from exc
        if "sandbox_mode" in data or "sandbox_workspace_write" in data:
            raise ManagementError(
                "worker_profile",
                f"Legacy sandbox settings conflict with permission profiles: {path}",
            )
        for section in ids:
            ids[section].update(data.get(section, {}))
    sections: dict[str, dict[str, Any]] = {
        section: {identity: {"enabled": False} for identity in sorted(identities)}
        for section, identities in ids.items()
    }
    # Codex can expose built-in task/worktree MCP namespaces without an
    # entry in local config. Disable the namespace alongside the feature gates;
    # a disabled MCP entry still needs a transport shape. Never replace a
    # configured transport or copy its credentials into argv.
    for namespace in ("codex_worktrees", "codex_tui"):
        sections["mcp_servers"].setdefault(namespace, {"enabled": False, "command": "false"})
    return [section + "=" + toml_value(values) for section, values in sections.items()]


def render(
    registry: Registry,
    task: dict[str, Any],
    *,
    prepare_operation: str,
    profile: str,
    cache: Path,
    delegation: str | None = None,
    hosts: list[str] | None = None,
    control_sockets: list[Path] | None = None,
    denied_paths: list[Path] | None = None,
    trust_checkout: bool = False,
) -> dict[str, Any]:
    """Create a protected settings snapshot. Does not launch or approve anything."""
    registry.reload_task(task)
    root = worktrees.require_present(task)
    validate_checkout(registry, task, worker=True)
    worktrees.require_prepared(task)
    preparation = registry.get("operation", prepare_operation)
    if (
        preparation["taskenv"] != task["id"]
        or preparation["command"] != "prepare"
        or preparation["state"] != "succeeded"
        or "handoff" not in preparation
    ):
        raise ManagementError("worker_unprepared", "Select a successful prepare for this taskenv")
    if preparation["handoff"].get("binding_revision", 0) != task.get("binding_revision", 0):
        raise ManagementError("worker_unprepared", "Environment was rebound; select a new prepare")
    config = load(root / CONFIG)
    if preparation["handoff"].get("configuration_digest") != digest(config):
        raise ManagementError(
            "worker_unprepared", "Recipe changed since prepare; review and prepare it"
        )
    codex = shutil.which("codex")
    if codex is None:
        raise ManagementError("missing_tool", "Codex is not installed")
    codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser().resolve()
    overrides = tool_overrides(root, profile, codex_home)
    if not cache.is_absolute():
        raise ManagementError("worker_cache", "Pass the observed absolute uv cache directory")
    cache = cache.resolve()
    protected_roots = [registry.root, Path(task["common"])]
    protected_roots.extend(
        Path(t["workspace_root"]) for t in registry.all("taskenv") if "workspace_root" in t
    )
    for protected_root in protected_roots:
        if cache.is_relative_to(protected_root) or protected_root.is_relative_to(cache):
            raise ManagementError(
                "worker_cache", "The uv cache cannot overlap state, workspaces or Git metadata"
            )
    identity = uuid.uuid4().hex
    permission = f"lodex-task-{identity}"
    runtime = runtime_base(registry, task) / "worker-runtime" / identity[:12]
    grant: dict[str, Any] | None = None
    routes: dict[str, str] = {}
    sockets: dict[str, str] = {}
    grant_root: str | None = None
    local_binding = False
    if delegation:
        grant = registry.get(KIND, delegation)
        if not grant["active"] or grant["taskenv"] != task["id"]:
            raise ManagementError("delegation_scope", "Select this taskenv's active delegation")
        if grant.get("configuration_digest") != digest(config):
            raise ManagementError("delegation_config_changed", "Review and create a new delegation")
        for name in grant["services"]:
            check_command(root, config["services"][name], config)
            spec = config["services"][name]
            if spec.get("allow_local_binding", "ready_port" in spec):
                local_binding = True
        grant_root = grant["runtime_root"]
        credential = Path(grant_root) / "client.json"
        Client(credential).request("list", target=task["id"])
        routes["LODEX_SERVICE_DELEGATION"] = str(credential)
        sockets[grant["socket"]] = "allow"
        sockets[grant_root] = "allow"
    private_dir(runtime)
    runtime_stat = runtime.stat()
    temporary = runtime / "tmp"
    private_dir(temporary)
    routes["TMPDIR"] = str(temporary)
    filesystem = {
        str(registry.root): "deny",
        str(task["common"]): "read",
        str(task["git_dir"]): "read",
        str(cache): "write",
        str(Path(tempfile.gettempdir()).resolve()): "read" if "workspace_root" in task else "deny",
    }
    if os.name == "posix":
        filesystem[str(Path("/tmp").resolve())] = "read" if "workspace_root" in task else "deny"
    for peer in registry.all("taskenv"):
        if "workspace_root" in peer:
            # A stable read-only parent also covers peers created after this
            # policy. Own paths are opened below; never grant the whole root.
            filesystem[peer["workspace_root"]] = "read"
        if peer["id"] != task["id"] and peer["path"] != str(root):
            # A registered source checkout can contain shared Git metadata. Keep
            # its metadata readable through the more specific rules above.
            filesystem[peer["path"]] = "read" if "workspace_root" in peer else "deny"
    filesystem.update({str(root): "write", str(runtime): "write"})
    if grant_root is not None:
        filesystem[grant_root] = "write"
    for protected in (".git", ".codex", ".agents", ".aws"):
        filesystem[str(root / protected)] = "read"
    for endpoint in control_sockets or []:
        if not endpoint.is_absolute():
            raise ManagementError("worker_socket", "Control socket paths must be absolute")
        filesystem[str(endpoint)] = "deny"
        sockets[str(endpoint)] = "deny"
    for denied in denied_paths or []:
        if not denied.is_absolute():
            raise ManagementError("worker_path", "Additional denied paths must be absolute")
        filesystem[str(denied.resolve())] = "deny"
    policy: dict[str, Any] = {
        "approval_policy": "never",
        "default_permissions": permission,
        "features.network_proxy": True,
        "features.hooks": False,
        "features.js_repl": False,
        "features.multi_agent": False,
        "features.multi_agent_v2": False,
        "features.multi_agent_v2_dynamic_tools": False,
        "features.apps": False,
        "features.plugins": False,
        "features.image_generation": False,
        "web_search": "disabled",
        "shell_environment_policy.inherit": "core",
        "shell_environment_policy.include_only": [
            "PATH",
            "HOME",
            "USER",
            "LOGNAME",
            "LANG",
            "LC_ALL",
            "SYSTEMROOT",
            *routes,
        ],
        "shell_environment_policy.set": routes,
        f"permissions.{permission}.extends": ":workspace",
        f"permissions.{permission}.filesystem": filesystem,
        # The proxy enforces the Unix-socket allowlist even without TCP hosts.
        f"permissions.{permission}.network.enabled": True,
        f"permissions.{permission}.network.allow_local_binding": local_binding,
        f"permissions.{permission}.network.domains": {host: "allow" for host in hosts or []},
        f"permissions.{permission}.network.unix_sockets": sockets,
    }
    if trust_checkout:
        # Only the explicit, reviewed checkout is trusted for this invocation.
        # No project trust entry is installed in the user's config file.
        policy["projects"] = {str(root): {"trust_level": "trusted"}}

    overrides.extend(f"{key}={toml_value(value)}" for key, value in policy.items())
    arguments = [argument for override in overrides for argument in ("-c", override)]
    result = {
        "version": 2,
        "id": identity,
        "taskenv": task["id"],
        "path": str(root),
        "task_identity": worktrees.binding(task),
        "runtime_root": str(runtime),
        "runtime_identity": {
            "root": str(runtime),
            "inode": [runtime_stat.st_dev, runtime_stat.st_ino],
        },
        "profile": profile,
        "launch_env": {"CODEX_HOME": str(codex_home)},
        "permission_profile": permission,
        "delegation": delegation,
        "trust_checkout": trust_checkout,
        "handoff": preparation["handoff"],
        "filesystem": filesystem,
        "sockets": sockets,
        "routes": routes,
        "agent_argv": [codex, "--no-daemon", "-p", profile, "-C", str(root), *arguments],
        "launcher_argv": [sys.executable, "-I", "-m", "lodex_cli.worker_session"],
        "sandbox_argv": [
            codex,
            "sandbox",
            "-p",
            profile,
            "-P",
            permission,
            "-C",
            str(root),
            *arguments,
        ],
    }
    destination = registry.root / "worker-policies" / f"{identity}.json"
    write_private(destination, json.dumps(result))
    return {**result, "policy_file": str(destination), "applied": False}


def read(registry: Registry, task: dict[str, Any], path: Path) -> dict[str, Any]:
    """Only a manager-owned, task-bound policy can wrap administrative cleanup."""
    registry.reload_task(task)
    expected = registry.root / "worker-policies"
    if path.is_symlink() or path.parent != expected or path.resolve().parent != expected:
        raise ManagementError("worker_policy", "Select a protected Lodex worker policy")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
        raise ManagementError("worker_policy", "Worker policy must be a private regular file")
    data = read_json(path)
    if (
        data.get("version") != 2
        or data.get("taskenv") != task["id"]
        or data.get("path") != task["path"]
    ):
        raise ManagementError(
            "worker_policy", "Unsupported or unrelated worker policy; regenerate it"
        )
    if data.get("task_identity") != worktrees.binding(task):
        raise ManagementError("identity_changed", "Worker policy binding changed; regenerate it")
    worktrees.require_present(task)
    validate_checkout(registry, task, worker=True)
    return data
