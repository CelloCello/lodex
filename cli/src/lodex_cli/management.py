"""Typed management commands calling the shared management core."""

from __future__ import annotations

import getpass
import os
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer

from lodex_cli.support import (
    Config,
    Json,
    Target,
    Yes,
    default_target,
    management_group,
    management_result,
)
from lodex_core.management import worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.store import Registry

project_app = management_group("Register repositories and initialize configuration.")
worktree_app = management_group("Create, attach, inspect and remove task environments.")
service_app = management_group("Start, stop and inspect configured services.")
operation_app = management_group("Inspect recorded repository command runs.")
env_app = management_group("Inspect resolved settings or export a dotenv file.")
port_app = management_group("Change declared port assignments.")
secret_app = management_group("Manage central secret values by stored name.")


@contextmanager
def registry(*, read_only: bool = False) -> Generator[Registry, None, None]:
    store = Registry(read_only=read_only)
    try:
        yield store
    finally:
        store.close()


def no_registry() -> bool:
    return not (
        Path(os.environ.get("LODEX_HOME", "~/.lodex")).expanduser() / "management.db"
    ).exists()


def resolve(store: Registry, target: str | None) -> dict[str, Any]:
    return worktrees.resolve(store, default_target(target))


@project_app.command("add")
def project_add(
    ctx: typer.Context,
    name: str,
    path: Path,
    config: Config = None,
    as_json: Json = False,
    display_name: Annotated[
        str | None, typer.Option(help="Display name; the positional NAME is the fixed project ID.")
    ] = None,
) -> int:
    """Register a repository and initialize missing configuration."""
    with registry() as store:
        return management_result(
            ctx,
            worktrees.project_add(store, name, path, config, project_name=display_name),
            as_json,
        )


@project_app.command("rename")
def project_rename(ctx: typer.Context, project: str, name: str, as_json: Json = False) -> int:
    """Change a project's display name; its ID and worktrees stay fixed."""
    with registry() as store:
        return management_result(ctx, worktrees.project_update(store, project, name), as_json)


@project_app.command("list")
def project_list(ctx: typer.Context, as_json: Json = False) -> int:
    """List registered projects."""
    if no_registry():
        return management_result(ctx, [], as_json)
    with registry(read_only=True) as store:
        return management_result(ctx, store.all("project"), as_json)


@project_app.command("pin")
def project_pin(
    ctx: typer.Context,
    project: str,
    unpin: Annotated[bool, typer.Option(help="Remove the pin.")] = False,
    as_json: Json = False,
) -> int:
    """Pin a project to the top of Console navigation."""
    with registry() as store:
        return management_result(
            ctx, worktrees.project_pin(store, project, pinned=not unpin), as_json
        )


@project_app.command("delete")
def project_delete(
    ctx: typer.Context, project: str, yes: Yes = False, as_json: Json = False
) -> int:
    """Preview or delete an empty project registration; keep all files."""
    with registry() as store:
        return management_result(ctx, worktrees.project_delete(store, project, yes=yes), as_json)


@worktree_app.command("create")
def worktree_create(
    ctx: typer.Context,
    project: str,
    ref: Annotated[str, typer.Option(help="Git ref to start from.")],
    branch: Annotated[str, typer.Option(help="New branch name.")],
    config: Config = None,
    as_json: Json = False,
) -> int:
    """Create a new branch and owned checkout; does not run prepare."""
    with registry() as store:
        return management_result(
            ctx, worktrees.create(store, project, ref, branch, config), as_json
        )


@worktree_app.command("attach")
def worktree_attach(
    ctx: typer.Context, project: str, path: Path, config: Config = None, as_json: Json = False
) -> int:
    """Register an existing checkout without taking ownership."""
    with registry() as store:
        return management_result(ctx, worktrees.attach(store, project, path, config), as_json)


@worktree_app.command("list")
def worktree_list(ctx: typer.Context, as_json: Json = False) -> int:
    """List registered environments and their inspection state."""
    with registry(read_only=True) as store:
        result = [worktrees.inspect(store, t) for t in store.all("taskenv")]
        return management_result(ctx, result, as_json)


@worktree_app.command("inspect")
def worktree_inspect(ctx: typer.Context, target: Target = None, as_json: Json = False) -> int:
    """Inspect an environment, including a missing checkout."""
    with registry(read_only=True) as store:
        return management_result(ctx, worktrees.inspect(store, resolve(store, target)), as_json)


@worktree_app.command("remove")
def worktree_remove(
    ctx: typer.Context,
    target: Target = None,
    yes: Yes = False,
    force: Annotated[bool, typer.Option("--force")] = False,
    as_json: Json = False,
) -> int:
    """Preview or delete an owned checkout, retaining its branch."""
    with registry() as store:
        result = worktrees.remove(store, resolve(store, target), yes=yes, force=force)
        return management_result(ctx, result, as_json)


@worktree_app.command("forget")
def worktree_forget(
    ctx: typer.Context, target: Target = None, yes: Yes = False, as_json: Json = False
) -> int:
    """Preview or remove registration without deleting resources."""
    with registry() as store:
        result = worktrees.forget(store, resolve(store, target), yes=yes)
        return management_result(ctx, result, as_json)


def context(ctx: typer.Context, target: Target = None, as_json: Json = False) -> int:
    """Resolve and inspect a present checkout with matching identity."""
    with registry(read_only=True) as store:
        task = resolve(store, target)
        worktrees.require_present(task)
        return management_result(ctx, worktrees.inspect(store, task), as_json)


def run_operation(
    ctx: typer.Context, name: str, target: str | None, config: Path | None, as_json: bool
) -> int:
    from lodex_core.management import operations

    with registry() as store:
        result = operations.run(store, resolve(store, target), name, source=config)
        return management_result(ctx, result, as_json, ok=result["state"] == "succeeded")


def prepare(
    ctx: typer.Context, target: Target = None, config: Config = None, as_json: Json = False
) -> int:
    """Run the repository's prepare command, supplying missing configuration."""
    return run_operation(ctx, "prepare", target, config, as_json)


def run(ctx: typer.Context, name: str, target: Target = None, as_json: Json = False) -> int:
    """Run a named repository command in the foreground."""
    return run_operation(ctx, name, target, None, as_json)


def cleanup(ctx: typer.Context, target: Target = None, as_json: Json = False) -> int:
    """Run the repository's cleanup command."""
    return run_operation(ctx, "cleanup", target, None, as_json)


@service_app.command("start")
def service_start(
    ctx: typer.Context, name: str, target: Target = None, as_json: Json = False
) -> int:
    """Start a configured service and check readiness."""
    from lodex_core.management import services

    with registry() as store:
        return management_result(ctx, services.start(store, resolve(store, target), name), as_json)


@service_app.command("stop")
def service_stop(
    ctx: typer.Context, name: str, target: Target = None, as_json: Json = False
) -> int:
    """Stop a managed service using its saved identity."""
    from lodex_core.management import services

    with registry() as store:
        task = resolve(store, target)
        return management_result(ctx, services.stop(store, task["id"], name), as_json)


@service_app.command("list")
def service_list(ctx: typer.Context, target: Target = None, as_json: Json = False) -> int:
    """List saved service records and refresh their state."""
    from lodex_core.management import services

    with registry(read_only=True) as store:
        return management_result(
            ctx, services.list_services(store, resolve(store, target)["id"]), as_json
        )


@service_app.command("inspect")
def service_inspect(
    ctx: typer.Context, name: str, target: Target = None, as_json: Json = False
) -> int:
    """Inspect and refresh a saved service record."""
    from lodex_core.management import services

    with registry(read_only=True) as store:
        task = resolve(store, target)
        result = services.refresh(store.get("service", f"{task['id']}-{name}"))
        return management_result(ctx, result, as_json)


@service_app.command("logs")
def service_logs(
    ctx: typer.Context, name: str, target: Target = None, as_json: Json = False
) -> int:
    """Read a service's recent log tail."""
    from lodex_core.management import services

    with registry(read_only=True) as store:
        task = resolve(store, target)
        return management_result(ctx, services.logs(store, task["id"], name), as_json)


@operation_app.command("list")
def operation_list(ctx: typer.Context, target: Target = None, as_json: Json = False) -> int:
    """List recorded command runs for an environment."""
    from lodex_core.management import operations

    with registry(read_only=True) as store:
        task = resolve(store, target)
        result = [
            operations.inspect_operation(store, o)
            for o in store.all("operation")
            if o["taskenv"] == task["id"]
        ]
        return management_result(ctx, result, as_json)


@operation_app.command("inspect")
def operation_inspect(ctx: typer.Context, id: str, as_json: Json = False) -> int:
    """Inspect a command run by operation ID."""
    from lodex_core.management import operations

    with registry(read_only=True) as store:
        result = operations.inspect_operation(store, store.get("operation", id))
        return management_result(ctx, result, as_json)


@operation_app.command("logs")
def operation_logs(ctx: typer.Context, id: str, as_json: Json = False) -> int:
    """Read a recorded command run's recent log tail."""
    from lodex_core.management import operations

    with registry(read_only=True) as store:
        record = operations.inspect_operation(store, store.get("operation", id))
        return management_result(ctx, operations.logs(record), as_json)


@env_app.command("show")
def env_show(ctx: typer.Context, target: Target = None, as_json: Json = False) -> int:
    """Show resolved settings and secret references, never secret values."""
    from lodex_core.management import settings

    with registry(read_only=True) as store:
        return management_result(ctx, settings.show(store, resolve(store, target)), as_json)


@env_app.command("export")
def env_export(
    ctx: typer.Context,
    target: Target = None,
    output: Annotated[str, typer.Option()] = ".env",
    as_json: Json = False,
) -> int:
    """Write resolved values, including secrets, to a protected dotenv file."""
    from lodex_core.management import settings

    with registry() as store:
        return management_result(
            ctx, settings.export(store, resolve(store, target), output), as_json
        )


@port_app.command("set")
def port_set(
    ctx: typer.Context, key: str, value: str, target: Target = None, as_json: Json = False
) -> int:
    """Change a declared port assignment without restarting services."""
    from lodex_core.management import settings

    with registry() as store:
        result = settings.set_port(store, resolve(store, target), key, value)
        return management_result(ctx, result, as_json)


@secret_app.command("list")
def secret_list(ctx: typer.Context, as_json: Json = False) -> int:
    """List central stored secret names without their values."""
    from lodex_core.management.secrets import SQLiteSecrets

    if no_registry():
        return management_result(ctx, [], as_json)
    with registry(read_only=True) as store:
        return management_result(ctx, SQLiteSecrets(store).list_names(), as_json)


@secret_app.command("set")
def secret_set(
    ctx: typer.Context,
    name: str,
    stdin: Annotated[bool, typer.Option("--stdin")] = False,
    as_json: Json = False,
) -> int:
    """Store a secret by name using hidden input or a trusted stdin pipe."""
    from lodex_core.management.secrets import SQLiteSecrets, reference_for_name

    with registry() as store:
        reference = reference_for_name(name)
        if stdin:
            value = sys.stdin.read().removesuffix("\n")
        else:
            if not sys.stdin.isatty():
                raise ManagementError("secret_input", "Use --stdin for piped secret input")
            value = getpass.getpass("Secret: ")
        SQLiteSecrets(store).set(reference, value)
        result = {"name": name, "reference": reference, "action": "set", "updated": True}
        return management_result(ctx, result, as_json)


@secret_app.command("remove")
def secret_remove(ctx: typer.Context, name: str, yes: Yes = False, as_json: Json = False) -> int:
    """Preview or delete a shared secret value by stored name."""
    from lodex_core.management.secrets import SQLiteSecrets, reference_for_name

    with registry() as store:
        reference = reference_for_name(name)
        result: dict[str, Any] = {"name": name, "reference": reference}
        if not yes:
            result["warning"] = "Deletes the SQLite secret shared by all references; use --yes"
        else:
            SQLiteSecrets(store).remove(reference)
            result.update(action="remove", updated=True)
        return management_result(ctx, result, as_json)


def register(app: typer.Typer) -> None:
    for name, group in (
        ("project", project_app),
        ("worktree", worktree_app),
        ("service", service_app),
        ("operation", operation_app),
        ("env", env_app),
        ("port", port_app),
        ("secret", secret_app),
    ):
        app.add_typer(group, name=name)
    for command in (context, prepare, run, cleanup):
        app.command()(command)
