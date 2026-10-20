"""Git-backed local repository and checkout identities."""

from __future__ import annotations

import hashlib
import os
import re
import socket
import subprocess
import uuid
from pathlib import Path
from typing import Any

from lodex_core.management.common import ManagementError, name, now
from lodex_core.management.project_config import CONFIG, load, supply
from lodex_core.management.store import Registry


def git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        text=True,
        capture_output=True,
        check=False,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    )
    if result.returncode:
        raise ManagementError("git_error", result.stderr.strip())
    return result.stdout.strip()


def identity(path: Path) -> dict[str, Any]:
    root = Path(git(path, "rev-parse", "--show-toplevel")).resolve()
    common = Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    git_dir = Path(git(root, "rev-parse", "--absolute-git-dir")).resolve()
    stat = root.stat()
    common_stat = common.stat()
    git_stat = git_dir.stat()
    return {
        "path": str(root),
        "common": str(common),
        "git_dir": str(git_dir),
        "inode": [stat.st_dev, stat.st_ino],
        "common_inode": [common_stat.st_dev, common_stat.st_ino],
        "git_inode": [git_stat.st_dev, git_stat.st_ino],
        "main": common == git_dir,
    }


def project_add(registry: Registry, label: str, path: Path, source: Path | None) -> dict[str, Any]:
    name(label)
    info = identity(path)
    root = Path(info["path"])
    source = source.resolve() if source is not None else None
    with registry.lock("registry"):
        existing = None
        for project in registry.all("project"):
            if project["id"] == label or project["common"] == info["common"]:
                if project["id"] == label and project["common"] == info["common"]:
                    if project["common_inode"] != info["common_inode"]:
                        raise ManagementError(
                            "identity_changed", "Registered repository was replaced"
                        )
                    existing = project
                    break
                raise ManagementError(
                    "already_registered", "Project name or local repository is registered"
                )
        configuration = supply(root, source)
        if existing is None:
            project = {
                "id": label,
                "common": info["common"],
                "common_inode": info["common_inode"],
                "source_checkout": info["path"],
                "source": str(root / CONFIG),
                "created_at": now(),
            }
            registry.put("project", project)
        else:
            project = existing
        result = {**project, "configuration": configuration}
        if configuration["method"] == "initialized":
            result["next_step"] = (
                f"Edit {root / CONFIG} to define repository commands and services "
                "before running them"
            )
        return result


def allocate(registry: Registry, task: dict[str, Any], config: dict[str, Any]) -> None:
    used = {
        p
        for item in registry.all("taskenv")
        if item["id"] != task["id"]
        for p in item["ports"].values()
    }
    for key, wanted in config["ports"].items():
        if key in task["ports"]:
            if wanted and wanted != task["ports"][key]:
                raise ManagementError(
                    "allocation_conflict", f"{key} already allocated; use port set"
                )
            continue
        candidates = [wanted] if wanted else range(20000, 50000)
        for candidate in candidates:
            if candidate in used or candidate in task["ports"].values():
                continue
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", candidate))
                except PermissionError as exc:
                    raise ManagementError(
                        "port_permission", "Permission denied binding local port"
                    ) from exc
                except OSError:
                    continue
            task["ports"][key] = candidate
            break
        else:
            raise ManagementError("port_conflict", f"No available port for {key}")


def attach(
    registry: Registry,
    project_id: str,
    path: Path,
    source: Path | None = None,
    *,
    owned: bool = False,
    task_id: str | None = None,
) -> dict[str, Any]:
    with registry.lock("registry"):
        return _attach_locked(registry, project_id, path, source, owned=owned, task_id=task_id)


def _attach_locked(
    registry: Registry,
    project_id: str,
    path: Path,
    source: Path | None,
    *,
    owned: bool,
    task_id: str | None,
) -> dict[str, Any]:
    """Register a checkout while the caller holds the registry lock."""
    project = registry.get("project", project_id)
    info = identity(path)
    if info["common"] != project["common"] or info["common_inode"] != project["common_inode"]:
        raise ManagementError(
            "wrong_repository", "Checkout belongs to a different local repository"
        )
    for task in registry.all("taskenv"):
        if task["path"] == info["path"]:
            with registry.lock(task["id"]):
                registry.reload_task(task)
                require_present(task)
                if task["project"] != project_id:
                    raise ManagementError("already_registered", "Checkout has another project")
                provenance = supply(Path(info["path"]), source or Path(project["source"]))
                if provenance["method"] == "copied":
                    task["config_source"] = provenance
                allocate(registry, task, load(Path(info["path"]) / CONFIG))
                task.pop("setup_error", None)
                registry.put("taskenv", task)
                return task
    provenance = supply(Path(info["path"]), source or Path(project["source"]))
    task = {
        **info,
        "id": task_id or uuid.uuid4().hex[:16],
        "project": project_id,
        "owned": owned,
        "ports": {},
        "config_source": provenance,
        "created_at": now(),
    }
    allocate(registry, task, load(Path(info["path"]) / CONFIG))
    registry.put("taskenv", task)
    return task


def creation_location(registry: Registry, project_id: str, branch: str) -> tuple[str, Path]:
    """Choose an unused ID and readable path while holding the registry lock."""
    slug = re.sub(r"[^a-z0-9]+", "-", branch.lower()).strip("-")[:64].rstrip("-") or "worktree"
    tasks = registry.all("taskenv")
    ids = {task["id"] for task in tasks}
    paths = {task["path"] for task in tasks}
    for _ in range(32):
        task_id = uuid.uuid4().hex[:16]
        path = registry.root / "projects" / project_id / f"{slug}--{task_id[:8]}"
        if task_id not in ids and str(path) not in paths and not os.path.lexists(path):
            return task_id, path
    raise ManagementError("path_conflict", "Could not allocate a unique worktree ID and path")


def create(
    registry: Registry, project_id: str, ref: str, branch: str, source: Path | None = None
) -> dict[str, Any]:
    project = registry.get("project", project_id)
    common = Path(project["common"])
    if [common.stat().st_dev, common.stat().st_ino] != project["common_inode"]:
        raise ManagementError("identity_changed", "Registered repository has been replaced")
    if branch.startswith("-"):
        raise ManagementError("invalid_branch", "Branch cannot start with a dash")
    commit = git(common, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
    # Acquire before Git creates anything and retain through registration/recovery.
    project_lock = f"project-{hashlib.sha256(project_id.encode()).hexdigest()[:56]}"
    with registry.lock(project_lock), registry.lock("registry"):
        task_id, path = creation_location(registry, project_id, branch)
        path.parent.mkdir(parents=True, exist_ok=True)
        git(common, "worktree", "add", "-b", branch, str(path), commit)
        try:
            return _attach_locked(registry, project_id, path, source, owned=True, task_id=task_id)
        except (ManagementError, OSError) as exc:
            # Preserve ownership when configuration fails after Git succeeds.
            task = {
                **identity(path),
                "id": task_id,
                "project": project_id,
                "owned": True,
                "ports": {},
                "config_source": {
                    "method": "unavailable",
                    "source": str(source or project["source"]),
                },
                "created_at": now(),
                "setup_error": str(exc),
            }
            registry.put("taskenv", task)
            raise ManagementError(
                "partial_create", f"Taskenv {task_id} exists at {path}; attach after fixing: {exc}"
            ) from exc


def state(task: dict[str, Any]) -> str:
    if not Path(task["path"]).exists():
        return "missing"
    try:
        actual = identity(Path(task["path"]))
    except (ManagementError, OSError):
        return "identity_changed"
    return "present" if all(actual[k] == task[k] for k in actual) else "identity_changed"


def require_present(task: dict[str, Any]) -> Path:
    status = state(task)
    if status != "present":
        raise ManagementError(status, f"Taskenv {task['id']} checkout is {status}: {task['path']}")
    return Path(task["path"])


def resolve(registry: Registry, selector: str) -> dict[str, Any]:
    if not Path(selector).is_absolute():
        return registry.get("taskenv", selector)
    path = Path(selector).resolve()
    matches = [
        t
        for t in registry.all("taskenv")
        if path == Path(t["path"]) or Path(t["path"]) in path.parents
    ]
    if not matches:
        raise ManagementError("not_found", f"No registered taskenv at {path}")
    task = max(matches, key=lambda t: len(t["path"]))
    root = Path(task["path"])
    # Exact/missing recorded roots remain addressable for inspect and service stop.
    # A descendant path must belong to this checkout, even for nested worktrees
    # sharing the same common Git directory. Probe the nearest existing directory
    # so a not-yet-created path cannot bypass the checkout boundary either.
    if path != root and root.exists():
        probe = path
        while not probe.is_dir() and probe != root:
            probe = probe.parent
        if Path(git(probe, "rev-parse", "--show-toplevel")).resolve() != root:
            raise ManagementError("not_found", f"No registered taskenv at {path}")
    return task


def inspect(registry: Registry, task: dict[str, Any]) -> dict[str, Any]:
    from lodex_core.management.operations import inspect_operation
    from lodex_core.management.services import list_services

    status = state(task)
    git_state: dict[str, Any] = {"branch": None, "head": None}
    if status == "present":
        try:
            branch = git(Path(task["path"]), "rev-parse", "--abbrev-ref", "HEAD")
            git_state = {
                "branch": None if branch == "HEAD" else branch,
                "head": git(Path(task["path"]), "rev-parse", "HEAD"),
            }
        except ManagementError as exc:
            git_state["git_error"] = str(exc)
    config_status = "missing"
    cleanup: dict[str, Any] = {
        "available": False,
        "reason": "Restore checkout/config/scripts or clean resources manually",
    }
    try:
        config = load(Path(task["path"]) / CONFIG)
        config_status = "valid"
        if status == "present" and "cleanup" in config["commands"]:
            from lodex_core.management.project_config import check_command

            check_command(Path(task["path"]), config["commands"]["cleanup"], config)
            cleanup = {"available": True, "command": ["lodex", "cleanup", "--target", task["id"]]}
        elif status == "present":
            cleanup["reason"] = "No cleanup command; add a repo command or clean resources manually"
    except ManagementError as exc:
        config_status = exc.code if config_status != "valid" else "valid"
        cleanup["reason"] = f"{exc}; restore the required files/tools or clean resources manually"
    operations = [
        inspect_operation(registry, o)
        for o in registry.all("operation")
        if o["taskenv"] == task["id"]
    ]
    known: dict[tuple[str, str], dict[str, Any]] = {}
    for operation in sorted(operations, key=lambda o: o["started_at"]):
        for resource in operation.get("result", {}).get("resources", []):
            known[(resource["kind"], resource["id"])] = {
                **resource,
                "observed_at": operation["observed_at"],
                "operation": operation["id"],
            }
    return {
        **task,
        **git_state,
        "state": status,
        "config_status": config_status,
        "services": list_services(registry, task["id"]),
        "operations": operations,
        "known_resources": list(known.values()),
        "cleanup": cleanup,
        "forget": {
            "command": ["lodex", "worktree", "forget", "--target", task["id"]],
            "warning": "Deregistration does not delete services or resources",
        },
    }


def forget(registry: Registry, task: dict[str, Any], *, yes: bool) -> dict[str, Any]:
    """Preview or remove registration, preserving checkout and resource records."""
    preview = inspect(registry, task)
    preview["warning"] = "Forgetting does not stop services or delete any external resources"
    if yes:
        with registry.lock(task["id"]):
            registry.delete("taskenv", task["id"])
        preview["forgotten"] = True
    return preview


def remove(registry: Registry, task: dict[str, Any], *, yes: bool, force: bool) -> dict[str, Any]:
    with registry.lock(task["id"]):
        registry.reload_task(task)
        root = require_present(task)
        current = inspect(registry, task)
        preview = {
            "id": task["id"],
            "path": str(root),
            "owned": task["owned"],
            "main": task["main"],
            "git_status": git(root, "status", "--porcelain"),
            "warning": "Deletes the directory including ignored files; retains the branch.",
            "services": current["services"],
            "operations": current["operations"],
            "known_resources": current["known_resources"],
            "cleanup": current["cleanup"],
        }
        if not yes:
            return preview
        if not task["owned"] or task["main"]:
            raise ManagementError(
                "protected_checkout", "Cannot remove an external or main checkout"
            )
        # Legacy URL-only records have no managed process and do not block removal.
        if any(
            s.get("state") not in ("stopped", "exited", "failed", "external")
            for s in preview["services"]
        ):
            raise ManagementError(
                "services_remaining", "Stop or resolve known services before remove"
            )
        args = ["worktree", "remove"] + (["--force"] if force else []) + [str(root)]
        git(Path(task["common"]), *args)
        # Retain evidence for subsequent inspect/forget; deletion is not resource cleanup.
        task["removed_at"] = now()
        registry.put("taskenv", task)
        return {**preview, "removed": True}
