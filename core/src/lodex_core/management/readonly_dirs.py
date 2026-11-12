"""Project-authorized, same-name links to shared source directories."""

from __future__ import annotations

import errno
import os
import stat
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lodex_core.management.common import ManagementError
from lodex_core.management.project_config import CONFIG, load
from lodex_core.management.store import Registry
from lodex_core.management.worker_sessions import inactive_session


def source_targets(
    registry: Registry, task: dict[str, Any], names: list[str], *, cleanup: bool = False
) -> dict[str, str]:
    if not names:
        return {}
    project = registry.get("project", task["project"])
    source = Path(project["source_checkout"])
    source_recipe = source / CONFIG
    if cleanup and not source_recipe.exists():
        return {}
    approved = load(source_recipe).get("readonly_dirs", [])
    # The source may withdraw a share while a task still has an older recipe.
    names = [name for name in names if name in approved]

    forbidden = {registry.root, Path(project["common"]), Path(task["git_dir"])}
    for peer in registry.all("taskenv"):
        if peer["path"] != str(source):
            forbidden.add(Path(peer["path"]))
        if "workspace_root" in peer:
            forbidden.add(Path(peer["workspace_root"]))
    targets: dict[str, str] = {}
    for name in names:
        try:
            target = (source / name).resolve(strict=not cleanup)
        except (OSError, RuntimeError) as exc:
            raise ManagementError(
                "readonly_dirs", f"Cannot resolve shared directory: {name}"
            ) from exc
        if (
            (not cleanup and not target.is_dir())
            or any(char in str(target) for char in "*?[]")  # Grant only literal policy paths.
            or source.is_relative_to(target)
            or any(
                part.casefold() in {".git", ".lodex", ".codex", ".agents", ".aws"}
                for part in target.parts
            )
            or any(target.is_relative_to(p) or p.is_relative_to(target) for p in forbidden)
        ):
            raise ManagementError("readonly_dirs", f"Unsafe shared directory: {name}")
        targets[name] = str(target)

    return targets


def _remove_empty_parent(parent: int, name: str, child: int) -> None:
    try:
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if os.path.samestat(current, os.fstat(child)):
            os.rmdir(name, dir_fd=parent)
    except OSError as exc:
        if exc.errno not in (errno.ENOENT, errno.ENOTEMPTY, errno.EEXIST):
            raise


def _parent(root: int, name: str, handles: ExitStack, undo: ExitStack | None = None) -> int:
    parent = root
    for part in Path(name).parts[:-1]:
        try:
            child = os.open(part, _DIR_FLAGS, dir_fd=parent)
        except FileNotFoundError:
            if undo is None:
                raise
            os.mkdir(part, dir_fd=parent)
            child = os.open(part, _DIR_FLAGS, dir_fd=parent)
            undo.callback(_remove_empty_parent, parent, part, child)
        handles.callback(os.close, child)
        parent = child
    return parent


_DIR_FLAGS = os.O_DIRECTORY | os.O_NOFOLLOW | os.O_RDONLY


@dataclass(frozen=True)
class _Entry:
    parent: int
    leaf: str

    def receipt(self) -> dict[str, Any] | None:
        try:
            info = os.stat(self.leaf, dir_fd=self.parent, follow_symlinks=False)
        except FileNotFoundError:
            return None
        receipt: dict[str, Any] = {"identity": [info.st_dev, info.st_ino, info.st_mtime_ns]}
        if stat.S_ISLNK(info.st_mode):
            receipt["target"] = os.readlink(self.leaf, dir_fd=self.parent)
        return receipt

    def remove_if(self, receipt: dict[str, Any]) -> None:
        if self.receipt() == receipt:
            os.unlink(self.leaf, dir_fd=self.parent)

    def restore(self, backup: _Entry, receipt: dict[str, Any]) -> None:
        if backup.receipt() == receipt:
            # A concurrent user replacement must never be overwritten by rollback.
            try:
                os.link(
                    backup.leaf,
                    self.leaf,
                    src_dir_fd=self.parent,
                    dst_dir_fd=self.parent,
                    follow_symlinks=False,
                )
            except FileExistsError:
                return
            backup.remove_if(receipt)


def check_links(checkout: Path, targets: dict[str, str]) -> None:
    with ExitStack() as handles:
        root = os.open(checkout, _DIR_FLAGS)
        handles.callback(os.close, root)
        for name, target in targets.items():
            try:
                parent = _parent(root, name, handles)
                if os.readlink(Path(name).name, dir_fd=parent) == target:
                    continue
            except OSError:
                pass
            raise ManagementError("readonly_dirs", f"Missing or conflicting shared link: {name}")


def shared_dirs(registry: Registry, task: dict[str, Any], names: list[str]) -> dict[str, str]:
    targets = source_targets(registry, task, names)
    if targets and task["path"] != registry.get("project", task["project"])["source_checkout"]:
        check_links(Path(task["path"]), targets)
    return targets


def prepare_links(registry: Registry, task: dict[str, Any], names: list[str]) -> dict[str, str]:
    targets = source_targets(registry, task, names)
    owned = task.get("owned_readonly_links", {})
    if (
        not (targets or owned)
        or task["path"] == registry.get("project", task["project"])["source_checkout"]
    ):
        return targets

    # Pin parent directory handles for the entire batch. Roll back namespace
    # changes before closing them. Existing, matching user links are borrowed.
    with ExitStack() as handles, ExitStack() as undo:
        root = os.open(task["path"], _DIR_FLAGS)
        handles.callback(os.close, root)
        new_owned = {}
        changes: list[tuple[str, _Entry | None, dict[str, Any] | None, str | None]] = []
        backups: list[tuple[_Entry, dict[str, Any]]] = []
        try:
            for name in sorted(owned.keys() | targets.keys()):
                want = targets.get(name)
                try:
                    parent = _parent(root, name, handles)
                except FileNotFoundError:
                    if want is not None:
                        changes.append((name, None, None, want))
                    continue
                except NotADirectoryError:
                    if want is None:
                        continue
                    raise
                entry = _Entry(parent, Path(name).name)
                receipt = entry.receipt()
                ours = bool(receipt) and receipt == owned.get(name)
                if want is not None and receipt and receipt.get("target") == want:
                    if ours:
                        new_owned[name] = receipt
                    continue
                if want is not None and receipt is not None and not ours:
                    raise ManagementError(
                        "readonly_dirs", f"Missing or conflicting shared link: {name}"
                    )
                if ours or want is not None:
                    changes.append((name, entry, receipt, want))

            if changes:
                handles.enter_context(inactive_session(registry.root, task["id"]))
            for name, location, receipt, want in changes:
                entry = location or _Entry(_parent(root, name, handles, undo), Path(name).name)
                if entry.receipt() != receipt:
                    raise ManagementError(
                        "readonly_dirs", f"Shared entry changed during prepare: {name}"
                    )
                if receipt:
                    backup = _Entry(entry.parent, ".lodex-link-" + uuid.uuid4().hex)
                    os.rename(
                        entry.leaf, backup.leaf, src_dir_fd=entry.parent, dst_dir_fd=entry.parent
                    )
                    moved = backup.receipt()
                    if moved != receipt:
                        if moved and "target" in moved:
                            entry.restore(backup, moved)
                        raise ManagementError(
                            "readonly_dirs",
                            f"Shared entry changed during prepare: {name}; inspect {backup.leaf}",
                        )
                    backups.append((backup, receipt))
                    undo.callback(entry.restore, backup, receipt)
                if want is not None:
                    os.symlink(want, entry.leaf, dir_fd=entry.parent)
                    created = entry.receipt()
                    if not created or created.get("target") != want:
                        raise ManagementError(
                            "readonly_dirs", f"Shared entry changed during prepare: {name}"
                        )
                    undo.callback(entry.remove_if, created)
                    new_owned[name] = created
            if changes:
                check_links(Path(task["path"]), targets)
            if new_owned != owned:
                updated = {**task, "owned_readonly_links": new_owned}
                registry.put("taskenv", updated)
                task.update(updated)
            undo.pop_all()
            for backup, receipt in backups:
                backup.remove_if(receipt)
        except OSError as exc:
            raise ManagementError("readonly_dirs", f"Cannot prepare shared links: {exc}") from exc
    return targets
