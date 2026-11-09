"""Typed management commands calling the shared management core."""

from __future__ import annotations

import getpass
import os
import signal
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
    require_registry_access()
    store = Registry(read_only=read_only)
    try:
        yield store
    finally:
        store.close()


def no_registry() -> bool:
    require_registry_access()
    return not (
        Path(os.environ.get("LODEX_HOME", "~/.lodex")).expanduser() / "management.db"
    ).exists()


def require_registry_access() -> None:
    if os.environ.get("LODEX_SERVICE_DELEGATION"):
        raise ManagementError("delegation_scope", "Delegation is limited to service operations")


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
    ctx: typer.Context,
    project: str,
    path: Path,
    config: Config = None,
    as_json: Json = False,
    rebind: Annotated[
        bool, typer.Option(help="Preview rebinding an existing environment at this path.")
    ] = False,
    yes: Yes = False,
    acknowledge_operation: Annotated[
        list[str] | None,
        typer.Option(
            "--acknowledge-operation",
            help="Confirm a stopped operation's unknown outcome; repeat per ID.",
        ),
    ] = None,
) -> int:
    """Register a checkout, or preview/confirm rebinding an existing environment."""
    with registry() as store:
        return management_result(
            ctx,
            worktrees.attach(
                store,
                project,
                path,
                config,
                rebind=rebind,
                yes=yes,
                acknowledge_operations=acknowledge_operation,
            ),
            as_json,
        )


@worktree_app.command("worker-config")
def worker_config(
    ctx: typer.Context,
    prepare_operation: Annotated[str, typer.Option(help="Successful prepare operation ID.")],
    profile: Annotated[str, typer.Option(help="Reviewed Codex config profile name.")],
    uv_cache: Annotated[Path, typer.Option(help="Observed absolute shared uv cache path.")],
    target: Target = None,
    delegation: Annotated[str | None, typer.Option(help="Active service delegation ID.")] = None,
    allow_host: Annotated[
        list[str] | None, typer.Option(help="Required application host; repeat.")
    ] = None,
    deny_socket: Annotated[
        list[Path] | None, typer.Option(help="Herdr/other control socket; repeat.")
    ] = None,
    deny_path: Annotated[
        list[Path] | None, typer.Option(help="Additional private path to deny; repeat.")
    ] = None,
    trust_checkout: Annotated[
        bool, typer.Option(help="Trust this reviewed checkout for this invocation only.")
    ] = False,
    as_json: Json = False,
) -> int:
    """Draft per-launch Codex settings; does not install settings or start an agent."""
    from lodex_cli import worker_policy

    with registry() as store:
        task = resolve(store, target)
        result = worker_policy.render(
            store,
            task,
            prepare_operation=prepare_operation,
            profile=profile,
            cache=uv_cache,
            delegation=delegation,
            hosts=allow_host,
            control_sockets=deny_socket,
            denied_paths=deny_path,
            trust_checkout=trust_checkout,
        )
        return management_result(ctx, result, as_json)


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


def cleanup(
    ctx: typer.Context,
    target: Target = None,
    worker_policy: Annotated[
        Path | None, typer.Option(help="Protected worker policy for restricted cleanup.")
    ] = None,
    as_json: Json = False,
) -> int:
    """Run cleanup in caller permissions, or in the selected worker's sandbox."""
    if worker_policy is None:
        return run_operation(ctx, "cleanup", target, None, as_json)
    from lodex_cli import worker_policy as policies
    from lodex_core.management import operations

    with registry() as store:
        task = resolve(store, target)
        policy = policies.read(store, task, worker_policy)

        def execute(result: Path) -> list[str]:
            # Only this operation's result file is opened beneath central state.
            # Its parent, records and logs remain inaccessible to checkout code.
            rule = f"permissions.{policy['permission_profile']}.filesystem=" + policies.toml_value(
                {**policy["filesystem"], str(result): "write"}
            )
            return [
                *policy["sandbox_argv"],
                "-c",
                rule,
                "--",
                sys.executable,
                "-I",
                "-m",
                "lodex_cli.cleanup_worker",
            ]

        result = operations.run(
            store,
            task,
            "cleanup",
            execution=execute,
            execution_env={**policy["routes"], **policy["launch_env"]},
            approved_secret_refs=policy["handoff"]["secret_refs"],
        )
        return management_result(ctx, result, as_json, ok=result["state"] == "succeeded")


@service_app.command("start")
def service_start(
    ctx: typer.Context, name: str, target: Target = None, as_json: Json = False
) -> int:
    """Start a configured service and check readiness."""
    from lodex_core.management import services

    delegated = worker_service(ctx, "start", name, target, as_json)
    if delegated is not None:
        return delegated
    with registry() as store:
        return management_result(ctx, services.start(store, resolve(store, target), name), as_json)


@service_app.command("stop")
def service_stop(
    ctx: typer.Context, name: str, target: Target = None, as_json: Json = False
) -> int:
    """Stop a managed service using its saved identity."""
    from lodex_core.management import services

    delegated = worker_service(ctx, "stop", name, target, as_json)
    if delegated is not None:
        return delegated
    with registry() as store:
        task = resolve(store, target)
        return management_result(ctx, services.stop(store, task["id"], name), as_json)


@service_app.command("list")
def service_list(ctx: typer.Context, target: Target = None, as_json: Json = False) -> int:
    """List saved service records and refresh their state."""
    from lodex_core.management import services

    delegated = worker_service(ctx, "list", None, target, as_json)
    if delegated is not None:
        return delegated
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

    delegated = worker_service(ctx, "inspect", name, target, as_json)
    if delegated is not None:
        return delegated
    with registry(read_only=True) as store:
        task = resolve(store, target)
        result = services.refresh(store.get("service", f"{task['id']}-{name}"))
        return management_result(ctx, services.with_pending_acks(store, result), as_json)


@service_app.command("retry-acks")
def service_retry_acks(
    ctx: typer.Context, name: str, target: Target = None, as_json: Json = False
) -> int:
    """Retry saved terminal acknowledgements without stopping the current service (manager)."""
    from lodex_core.management import services

    with registry() as store:
        task = resolve(store, target)
        return management_result(ctx, services.retry_acks(store, task["id"], name), as_json)


@service_app.command("logs")
def service_logs(
    ctx: typer.Context, name: str, target: Target = None, as_json: Json = False
) -> int:
    """Read a service's recent log tail."""
    from lodex_core.management import services

    delegated = worker_service(ctx, "logs", name, target, as_json)
    if delegated is not None:
        return delegated
    with registry(read_only=True) as store:
        task = resolve(store, target)
        return management_result(ctx, services.logs(store, task["id"], name), as_json)


def worker_service(
    ctx: typer.Context, action: str, name: str | None, target: str | None, as_json: bool
) -> int | None:
    credential = os.environ.get("LODEX_SERVICE_DELEGATION")
    if not credential:
        return None
    from lodex_core.management.delegation import Client

    return management_result(ctx, Client(Path(credential)).perform(action, name, target), as_json)


@service_app.command("delegate")
def service_delegate(
    ctx: typer.Context,
    service: Annotated[
        list[str], typer.Option("--service", help="Allow this service; repeat explicitly.")
    ],
    target: Target = None,
    as_json: Json = False,
) -> int:
    """Serve one taskenv's service delegation in the foreground until revoked or stopped."""
    from lodex_core.management.delegation import Controller

    with registry() as store:
        controller = Controller(store, resolve(store, target), service)

        def interrupted(signum: int, frame: object) -> None:
            raise KeyboardInterrupt

        previous = signal.signal(signal.SIGTERM, interrupted)

        def ready(info: dict[str, Any]) -> None:
            management_result(ctx, info, as_json)
            sys.stdout.flush()

        try:
            controller.serve(ready)
        except KeyboardInterrupt:
            pass
        finally:
            controller.close()
            signal.signal(signal.SIGTERM, previous)
    return 0


@service_app.command("revoke")
def service_revoke(ctx: typer.Context, identity: str, as_json: Json = False) -> int:
    """Revoke a service delegation; leave its services available for manager takeover."""
    from lodex_core.management.delegation import revoke

    with registry() as store:
        return management_result(ctx, revoke(store, identity), as_json)


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
