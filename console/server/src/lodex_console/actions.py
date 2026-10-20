"""Finite console actions using the same core functions as the CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lodex_core.management import operations, services, settings, worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.project_config import CONFIG, load
from lodex_core.management.secrets import SQLiteSecrets, reference_for_name
from lodex_core.management.store import Registry


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal[
        "project.add",
        "worktree.create",
        "worktree.attach",
        "worktree.remove",
        "worktree.forget",
        "prepare",
        "run",
        "cleanup",
        "service.start",
        "service.stop",
        "service.logs",
        "operation.logs",
        "env.export",
        "port.set",
        "secret.set",
        "secret.remove",
    ]
    target: str | None = None
    name: str | None = None
    path: str | None = None
    project: str | None = None
    ref: str | None = None
    branch: str | None = None
    config: str | None = None
    value: str | None = Field(default=None, repr=False, max_length=65536)
    output: str = ".env"
    yes: bool = False
    force: bool = False

    def require(self, key: str) -> str:
        value = getattr(self, key)
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ManagementError("invalid_input", f"Provide {key}")
        return value

    def absolute_path(self, key: str) -> Path:
        path = Path(self.require(key))
        if not path.is_absolute():
            raise ManagementError("invalid_input", f"{key} must be an absolute path")
        return path


def execute(store: Registry, request: Action) -> Any:
    action = request.action
    source = request.absolute_path("config") if request.config else None
    if action == "project.add":
        return worktrees.project_add(
            store, request.require("name"), request.absolute_path("path"), source
        )
    if action == "worktree.create":
        return worktrees.create(
            store,
            request.require("project"),
            request.require("ref"),
            request.require("branch"),
            source,
        )
    if action == "worktree.attach":
        return worktrees.attach(
            store, request.require("project"), request.absolute_path("path"), source
        )
    if action.startswith("secret."):
        name = request.require("name")
        reference = reference_for_name(name)
        if action == "secret.set":
            SQLiteSecrets(store).set(reference, request.require("value"))
        elif not request.yes:
            return {"name": name, "warning": "Deletes a secret shared by every reference"}
        else:
            SQLiteSecrets(store).remove(reference)
        return {"name": name, "updated": True}
    if action == "operation.logs":
        return operations.logs(
            operations.inspect_operation(store, store.get("operation", request.require("target")))
        )
    task = worktrees.resolve(store, request.require("target"))
    if action in ("prepare", "run", "cleanup"):
        command = request.require("name") if action == "run" else action
        return operations.run(store, task, command, source=source)
    if action == "service.start":
        return services.start(store, task, request.require("name"))
    if action == "service.stop":
        return services.stop(store, task["id"], request.require("name"))
    if action == "service.logs":
        return services.logs(store, task["id"], request.require("name"))
    if action == "env.export":
        return settings.export(store, task, request.output)
    if action == "port.set":
        return settings.set_port(store, task, request.require("name"), request.require("value"))
    if action == "worktree.remove":
        return worktrees.remove(store, task, yes=request.yes, force=request.force)
    return worktrees.forget(store, task, yes=request.yes)


def overview(root: Path) -> dict[str, Any]:
    if not (root / "management.db").exists():
        return {"projects": [], "taskenvs": [], "secrets": []}
    store = Registry(root, read_only=True)
    try:
        return {
            "projects": store.all("project"),
            "taskenvs": [worktrees.inspect(store, task) for task in store.all("taskenv")],
            "secrets": SQLiteSecrets(store).list_names(),
        }
    finally:
        store.close()


def detail(root: Path, target: str) -> dict[str, Any]:
    store = Registry(root, read_only=True)
    try:
        task = worktrees.resolve(store, target)
        result = worktrees.inspect(store, task)
        result["configuration_path"] = str(Path(task["path"]) / CONFIG)
        try:
            config = load(worktrees.require_present(task) / CONFIG)
            # Expose names and non-secret values, never arbitrary argv or secret values.
            result["commands"] = list(config["commands"])
            result["configured_services"] = list(config["services"])
            result["environment"] = settings.show(store, task)
        except ManagementError as exc:
            result["configuration_error"] = {"code": exc.code, "message": str(exc)}
        return result
    finally:
        store.close()
