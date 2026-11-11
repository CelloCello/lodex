"""Locations for new task workspaces, independent of protected manager state.

Existing records are authoritative. Changing configuration never relocates a
checkout, runtime, service, or an already issued worker policy.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from lodex_core.management.common import ManagementError, name
from lodex_core.management.store import Registry
from lodex_core.management.worker_sessions import inactive_session


def configured_root(registry: Registry) -> Path:
    value = os.environ.get("LODEX_WORKSPACE_ROOT")
    config = registry.root / "management.toml"
    if value is None and config.exists():
        try:
            data = tomllib.loads(config.read_text())
            if set(data) - {"workspace_root"}:
                raise ValueError("Unknown management setting")
            value = data.get("workspace_root")
        except (OSError, ValueError) as exc:
            raise ManagementError("workspace_config", "Cannot read management.toml") from exc
    if value is None:
        value = str(registry.root.with_name(registry.root.name + "-workspaces"))
    if not isinstance(value, str) or not value.strip():
        raise ManagementError("workspace_config", "workspace_root must be a nonempty path")
    root = Path(value).expanduser()
    if not root.is_absolute():
        raise ManagementError("workspace_config", "workspace_root must be absolute")
    root = root.resolve()
    if root.is_relative_to(registry.root) or registry.root.is_relative_to(root):
        raise ManagementError("workspace_config", "Workspace and management roots must not overlap")
    for task in registry.all("taskenv"):
        if root.is_relative_to(Path(task["path"])) or root.is_relative_to(Path(task["common"])):
            raise ManagementError(
                "workspace_config", "Workspace root cannot be inside a checkout or Git metadata"
            )
    for project in registry.all("project"):
        if root == Path(project["source_checkout"]).resolve() or root.is_relative_to(
            Path(project["common"]).resolve()
        ):
            raise ManagementError(
                "workspace_config",
                "Workspace root cannot equal a project checkout or be inside Git metadata",
            )
    return root


def overlapping_tasks(peers: list[dict[str, Any]], checkout: Path) -> Iterator[dict[str, Any]]:
    for peer in peers:
        other = Path(peer["path"]).resolve()
        if checkout.is_relative_to(other) or other.is_relative_to(checkout):
            yield peer


@contextmanager
def registration_locks(registry: Registry, checkout: Path) -> Iterator[None]:
    """The caller holds the registry lock. Pin overlapping leases through registration."""
    from lodex_core.management.services import services_retired

    checkout = checkout.resolve()
    with ExitStack() as held:
        for peer in overlapping_tasks(registry.all("taskenv"), checkout):
            if peer["path"] != str(checkout):  # Same-path rebind handles its own worker.
                held.enter_context(registry.lock(peer["id"]))  # Includes running cleanup.
                held.enter_context(inactive_session(registry.root, peer["id"]))
                if not services_retired(registry, peer["id"]):
                    raise ManagementError(
                        "services_remaining", f"Stop and acknowledge overlapping task {peer['id']}"
                    )
        yield


def validate_checkout(registry: Registry, task: dict[str, Any], *, worker: bool = False) -> None:
    """Reject writable checkouts that overlap another task or shared runtime space.

    Use saved roots, not current configuration, when checking existing tasks.
    This also guards policy issuance for registrations made by older versions.
    """
    checkout = Path(task["path"]).resolve()
    # Legacy tasks keep central runtime locations. Protect those namespaces too
    # while continuing to allow their historical projects/ checkout paths.
    for reserved in ("worker-runtime", "delegated", "delegation-sockets"):
        runtime = (registry.root / reserved).resolve()
        if checkout.is_relative_to(runtime) or runtime.is_relative_to(checkout):
            raise ManagementError(
                "workspace_overlap", "Checkout overlaps a legacy runtime namespace"
            )
    peers = registry.all("taskenv")
    roots = {Path(t["workspace_root"]).resolve() for t in [*peers, task] if "workspace_root" in t}
    for root in roots:
        if root.is_relative_to(checkout) or any(
            checkout.is_relative_to(root / reserved) for reserved in (".r", "delegation-sockets")
        ):
            raise ManagementError(
                "workspace_overlap",
                "Checkout overlaps a shared workspace root or runtime namespace",
            )
    # General management supports nested checkouts for target resolution, but
    # they cannot be independently writable isolated worker environments.
    if worker and any(peer["id"] != task["id"] for peer in overlapping_tasks(peers, checkout)):
        raise ManagementError("workspace_overlap", "Task checkouts must not overlap")


def runtime_base(registry: Registry, task: dict[str, Any]) -> Path:
    """Short paths keep delegated Unix sockets within macOS sun_path limits."""
    if "workspace_root" not in task:
        return registry.root  # Preserve legacy runtime/policy recovery.
    return Path(task["workspace_root"]) / ".r" / name(task["id"])
