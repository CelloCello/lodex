"""Git-backed local repository and checkout identities."""

from __future__ import annotations

import hashlib
import os
import re
import socket
import subprocess
import unicodedata
import uuid
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from lodex_core.management.common import ManagementError, name, now
from lodex_core.management.project_config import CONFIG, load, supply
from lodex_core.management.store import Registry
from lodex_core.management.worker_sessions import inactive_session
from lodex_core.management.workspace import configured_root, registration_locks, validate_checkout

IDENTITY_FIELDS = ("path", "common", "git_dir", "main")


def binding(task: dict[str, Any]) -> dict[str, Any]:
    """Stable directory association, including explicit rebinds, never device/inode IDs."""
    return {key: task[key] for key in IDENTITY_FIELDS} | {
        "binding_revision": task.get("binding_revision", 0)
    }


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
    if common != git_dir:
        paths = {
            str(Path(field.removeprefix("worktree ")).resolve())
            for field in git(common, "worktree", "list", "--porcelain", "-z").split("\0")
            if field.startswith("worktree ")
        }
        if str(root) not in paths:
            raise ManagementError(
                "identity_changed", "Directory is not listed by its Git repository"
            )
        backlink = Path((git_dir / "gitdir").read_text().rstrip("\n"))
        if not backlink.is_absolute():
            backlink = git_dir / backlink
        if backlink.resolve() != (root / ".git").resolve():
            raise ManagementError("identity_changed", "Git directory points to another worktree")
    return {
        "path": str(root),
        "common": str(common),
        "git_dir": str(git_dir),
        "main": common == git_dir,
    }


def display_name(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 120 or any(unicodedata.category(char) == "Cc" for char in value):
        raise ManagementError(
            "invalid_name", "Use a project name of 1-120 characters without control characters"
        )
    return value


def project_update(registry: Registry, project_id: str, new_name: str) -> dict[str, Any]:
    label = display_name(new_name)
    with registry.lock("registry"):
        project = registry.get("project", project_id)
        project["display_name"] = label
        registry.put("project", project)
        return project


def project_pin(registry: Registry, project_id: str, *, pinned: bool) -> dict[str, Any]:
    with registry.lock("registry"):
        project = registry.get("project", project_id)
        project["pinned"] = pinned
        registry.put("project", project)
        return project


def project_delete(registry: Registry, project_id: str, *, yes: bool) -> dict[str, Any]:
    with registry.lock("registry"):
        project = registry.get("project", project_id)
        count = sum(task["project"] == project_id for task in registry.all("taskenv"))
        if count:
            raise ManagementError(
                "project_not_empty",
                f"Project {project_id} still has {count} environment(s). "
                "Unregister them before deleting the project.",
            )
        if yes:
            registry.delete("project", project_id)
        return {
            "project": project_id,
            "display_name": project.get("display_name") or project_id,
            "source_checkout": project["source_checkout"],
            "warning": (
                "Deletes only the project registration. Repository, worktrees and files remain."
            ),
            "removed": yes,
        }


def project_add(
    registry: Registry,
    label: str,
    path: Path,
    source: Path | None,
    *,
    project_name: str | None = None,
) -> dict[str, Any]:
    name(label)
    title = display_name(project_name) if project_name is not None else None
    info = identity(path)
    root = Path(info["path"])
    source = source.resolve() if source is not None else None
    with registry.lock("registry"):
        existing = None
        for project in registry.all("project"):
            if project["id"] == label or project["common"] == info["common"]:
                if project["id"] == label and project["common"] == info["common"]:
                    existing = project
                    break
                raise ManagementError(
                    "already_registered",
                    (
                        "This repository is already registered as "
                        f"{project.get('display_name') or project['id']} (ID: {project['id']})."
                        if project["common"] == info["common"]
                        else f"Project ID {label} is already in use. Choose a different project ID."
                    ),
                    details={"existing_project": project["id"]},
                )
        configuration = supply(root, source)
        if existing is None:
            project = {
                "id": label,
                "common": info["common"],
                "source_checkout": info["path"],
                "source": str(root / CONFIG),
                "created_at": now(),
            }
            if title is not None:
                project["display_name"] = title
            registry.put("project", project)
        else:
            project = existing
        result = {**project, "configuration": configuration}
        if existing is not None:
            result["already_registered"] = True
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
    rebind: bool = False,
    yes: bool = False,
    acknowledge_operations: list[str] | None = None,
) -> dict[str, Any]:
    if (yes or acknowledge_operations) and not rebind:
        raise ManagementError("invalid_input", "Confirmation options require --rebind for attach")
    with registry.lock("registry"):
        info = identity(path)
        with registration_locks(registry, Path(info["path"])):
            return _attach_locked(
                registry,
                project_id,
                info,
                source,
                owned=owned,
                task_id=task_id,
                rebind=rebind,
                yes=yes,
                acknowledge_operations=acknowledge_operations,
            )


def _attach_locked(
    registry: Registry,
    project_id: str,
    info: dict[str, Any],
    source: Path | None,
    *,
    owned: bool,
    task_id: str | None,
    rebind: bool = False,
    yes: bool = False,
    acknowledge_operations: list[str] | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """Register a checkout while the caller holds the registry lock."""
    project = registry.get("project", project_id)
    if info["common"] != project["common"]:
        raise ManagementError("wrong_repository", "Worktree belongs to a different repository")
    for task in registry.all("taskenv"):
        if task["path"] == info["path"]:
            with registry.lock(task["id"]), ExitStack() as held:
                registry.reload_task(task)
                if task["project"] != project_id:
                    raise ManagementError(
                        "already_registered", "Worktree is registered to another project"
                    )
                if rebind:
                    from lodex_core.management.operations import inspect_operation
                    from lodex_core.management.services import services_retired

                    held.enter_context(inactive_session(registry.root, task["id"]))
                    operations = [
                        op for op in registry.all("operation") if op["taskenv"] == task["id"]
                    ]

                    if (
                        any(
                            grant["taskenv"] == task["id"] and grant["active"]
                            for grant in registry.all("service-delegation")
                        )
                        or any(registry.busy(f"op-{op['id']}") for op in operations)
                        or not services_retired(registry, task["id"])
                    ):
                        raise ManagementError(
                            "busy",
                            "Stop services, revoke delegations and resolve operations "
                            "before rebind",
                        )
                    requested = set(acknowledge_operations or [])
                    if requested - {op["id"] for op in operations}:
                        raise ManagementError(
                            "invalid_input",
                            "Acknowledge only operation IDs belonging to this environment",
                        )
                    receipts = dict(task.get("rebind_acknowledgements", {}))
                    unresolved = [
                        inspect_operation(registry, op)
                        for op in operations
                        if op["state"] not in ("succeeded", "failed", "interrupted")
                        and op["id"] not in receipts
                    ]
                    pending = [op["id"] for op in unresolved if op["id"] not in requested]
                    revision = task.get("binding_revision", 0) + 1
                    for op in unresolved:
                        if op["id"] in requested:
                            receipts[op["id"]] = {
                                "observed_at": now(),
                                "binding_revision": revision,
                            }
                    updated = {
                        **task,
                        **info,
                        "owned": False,
                        "prepare_required": True,
                        "binding_revision": revision,
                        "rebind_acknowledgements": receipts,
                    }
                    validate_checkout(registry, updated)
                    preview = {
                        "id": task["id"],
                        "project": project_id,
                        "path": info["path"],
                        "before": binding(task),
                        "after": binding(updated),
                        "rebound": False,
                        "previous_owned": task["owned"],
                        "owned": False,
                        "prepare_required": True,
                        "unresolved_operations": [
                            {key: op.get(key) for key in ("id", "state", "exit_code", "error")}
                            for op in unresolved
                        ],
                        "required_acknowledgements": pending,
                        "warning": (
                            "Keeps ID, ports and history; drops deletion ownership and "
                            "requires prepare. Old worker policies must be regenerated."
                        ),
                    }
                    if not yes:
                        return preview
                    if pending:
                        raise ManagementError(
                            "unresolved_operations",
                            "Inspect unknown operations, confirm their processes stopped, then use "
                            "--acknowledge-operation ID for each before rebind",
                            details=preview,
                        )
                    task = updated
                    for key in ("inode", "common_inode", "git_inode", "removed_at", "setup_error"):
                        task.pop(key, None)
                else:
                    require_present(task)
                    validate_checkout(registry, task)
                provenance = supply(Path(info["path"]), source or Path(project["source"]))
                if provenance["method"] == "copied":
                    task["config_source"] = provenance
                allocate(registry, task, load(Path(info["path"]) / CONFIG))
                task.pop("setup_error", None)
                registry.put("taskenv", task)
                return {**task, "rebound": True} if rebind else task
    if rebind:
        raise ManagementError("not_found", "Rebind requires a registered environment at this path")
    task = {
        **info,
        "id": task_id or uuid.uuid4().hex[:16],
        "project": project_id,
        "owned": owned,
        "workspace_root": str(workspace_root or configured_root(registry)),
        "ports": {},
        "created_at": now(),
    }
    validate_checkout(registry, task)
    task["config_source"] = supply(Path(info["path"]), source or Path(project["source"]))
    allocate(registry, task, load(Path(info["path"]) / CONFIG))
    registry.put("taskenv", task)
    return task


def creation_location(registry: Registry, project_id: str, branch: str) -> tuple[str, Path]:
    """Choose an unused ID and readable path while holding the registry lock."""
    slug = re.sub(r"[^a-z0-9]+", "-", branch.lower()).strip("-")[:64].rstrip("-") or "worktree"
    tasks = registry.all("taskenv")
    ids = {task["id"] for task in tasks}
    paths = {task["path"] for task in tasks}
    workspace_root = configured_root(registry)
    for _ in range(32):
        task_id = uuid.uuid4().hex[:16]
        path = workspace_root / project_id / f"{slug}--{task_id[:8]}"
        if task_id not in ids and str(path) not in paths and not os.path.lexists(path):
            validate_checkout(
                registry, {"id": task_id, "path": str(path), "workspace_root": str(workspace_root)}
            )
            return task_id, path
    raise ManagementError("path_conflict", "Could not allocate a unique worktree ID and path")


def create(
    registry: Registry, project_id: str, ref: str, branch: str, source: Path | None = None
) -> dict[str, Any]:
    if branch.startswith("-"):
        raise ManagementError("invalid_branch", "Branch cannot start with a dash")
    # Acquire before Git creates anything and retain through registration/recovery.
    project_lock = f"project-{hashlib.sha256(project_id.encode()).hexdigest()[:56]}"
    with registry.lock(project_lock), registry.lock("registry"), ExitStack() as held:
        project = registry.get("project", project_id)
        common = Path(project["common"])
        actual_common = Path(
            git(common, "rev-parse", "--path-format=absolute", "--git-common-dir")
        ).resolve()
        if str(actual_common) != project["common"]:
            raise ManagementError("identity_changed", "Registered Git common directory changed")
        commit = git(common, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
        task_id, path = creation_location(registry, project_id, branch)
        held.enter_context(registration_locks(registry, path))
        path.parent.mkdir(parents=True, exist_ok=True)
        git(common, "worktree", "add", "-b", branch, str(path), commit)
        try:
            task = _attach_locked(
                registry,
                project_id,
                identity(path),
                source,
                owned=True,
                task_id=task_id,
                workspace_root=path.parent.parent,
            )
            task.update(base_commit=commit, base_ref=ref)
            registry.put("taskenv", task)
            return task
        except (ManagementError, OSError) as exc:
            # Preserve ownership when configuration fails after Git succeeds.
            task = {
                **identity(path),
                "id": task_id,
                "project": project_id,
                "owned": True,
                "workspace_root": str(path.parent.parent),
                "base_commit": commit,
                "base_ref": ref,
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
                "partial_create",
                f"Environment {task_id} exists at {path}; use worktree attach after fixing: {exc}",
            ) from exc


def observe(task: dict[str, Any]) -> dict[str, Any]:
    """Report recoverable directory problems without discarding saved records."""
    root = Path(task["path"])
    try:
        root.stat()
    except (FileNotFoundError, NotADirectoryError):
        return {"state": "missing", "reason": "Registered directory does not exist"}
    except OSError as exc:
        return {"state": "unavailable", "reason": str(exc)}
    try:
        actual = identity(root)
    except (FileNotFoundError, NotADirectoryError):
        return {"state": "identity_changed", "reason": "Git association metadata is missing"}
    except OSError as exc:
        return {"state": "unavailable", "reason": str(exc)}
    except ManagementError as exc:
        try:
            (root / ".git").stat()
        except (FileNotFoundError, NotADirectoryError):
            return {"state": "identity_changed", "reason": "Directory is not a Git worktree"}
        except OSError as error:
            return {"state": "unavailable", "reason": str(error)}
        return {
            "state": "identity_changed" if exc.code == "identity_changed" else "unavailable",
            "reason": str(exc),
        }
    if any(actual[key] != task[key] for key in IDENTITY_FIELDS):
        return {
            "state": "identity_changed",
            "reason": "Git worktree association changed",
            "actual": actual,
        }
    return {"state": "present"}


def state(task: dict[str, Any]) -> str:
    return str(observe(task)["state"])


def require_present(task: dict[str, Any]) -> Path:
    observation = observe(task)
    if observation["state"] != "present":
        raise ManagementError(
            observation["state"],
            f"Environment {task['id']}: {observation['reason']}: {task['path']}",
            details={
                **observation,
                "rebind": [
                    "lodex",
                    "worktree",
                    "attach",
                    task["project"],
                    task["path"],
                    "--rebind",
                ],
            },
        )
    return Path(task["path"])


def require_prepared(task: dict[str, Any]) -> None:
    if task.get("prepare_required"):
        raise ManagementError("prepare_required", "Environment was rebound; run prepare first")


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
        raise ManagementError("not_found", f"No registered environment at {path}")
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
            raise ManagementError("not_found", f"No registered environment at {path}")
    return task


def inspect(registry: Registry, task: dict[str, Any]) -> dict[str, Any]:
    from lodex_core.management.operations import inspect_operation
    from lodex_core.management.services import list_services

    observation = observe(task)
    status = observation["state"]
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
        "reason": "Restore the worktree, configuration and scripts, or clean resources manually",
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
        "identity": observation,
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
        with registry.lock(task["id"]), inactive_session(registry.root, task["id"]):
            require_inactive(registry, task)
            registry.delete("taskenv", task["id"])
        preview["forgotten"] = True
    return preview


def require_inactive(registry: Registry, task: dict[str, Any]) -> None:
    """Check resources while the caller holds the task and inactive-session locks."""
    if any(
        op["taskenv"] == task["id"] and registry.busy(f"op-{op['id']}")
        for op in registry.all("operation")
    ):
        raise ManagementError("busy", "An operation is still running")
    from lodex_core.management.services import services_retired

    if not services_retired(registry, task["id"]):
        raise ManagementError(
            "services_remaining", "Stop services and acknowledge terminal results first"
        )
    if any(g["taskenv"] == task["id"] and g["active"] for g in registry.all("service-delegation")):
        raise ManagementError("delegation_active", "Revoke service delegation before retirement")


def remove(registry: Registry, task: dict[str, Any], *, yes: bool, force: bool) -> dict[str, Any]:
    with registry.lock(task["id"]), ExitStack() as held:
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
        held.enter_context(inactive_session(registry.root, task["id"]))
        require_inactive(registry, task)
        if not task["owned"] or task["main"]:
            raise ManagementError(
                "protected_checkout", "Cannot remove an attached or main worktree"
            )
        args = ["worktree", "remove"] + (["--force"] if force else []) + [str(root)]
        git(Path(task["common"]), *args)
        # Retain evidence for subsequent inspect/forget; deletion is not resource cleanup.
        task["removed_at"] = now()
        registry.put("taskenv", task)
        return {**preview, "removed": True}
