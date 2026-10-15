from __future__ import annotations

import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from lodex_core.management import project_config, worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.secrets import SQLiteSecrets
from lodex_core.management.store import SCHEMA_VERSION, Registry

from .support.management import register


def test_inspect_reports_current_branch_and_detached_head(registry: Registry, repo: Path) -> None:
    (repo / project_config.CONFIG).write_text("schema_version=1\n")
    worktrees.project_add(registry, "sample", repo, None)
    task = worktrees.attach(registry, "sample", repo, None)
    worktrees.git(repo, "switch", "-c", "feature/current")
    info = worktrees.inspect(registry, task)
    assert info["branch"] == "feature/current"
    worktrees.git(repo, "checkout", "--detach")
    detached = worktrees.inspect(registry, task)
    assert detached["branch"] is None and detached["head"] == info["head"]


@pytest.mark.parametrize("missing", [False, True])
def test_forget_only_removes_registration_after_confirmation(
    registry: Registry, repo: Path, missing: bool
) -> None:
    task = register(registry, repo)
    SQLiteSecrets(registry).set("secret:shared", "fixture-secret")
    directory = repo.parent / "saved-service"
    directory.mkdir()
    (directory / "status.json").write_text('{"state":"stopped"}')
    service = {
        "id": f"{task['id']}-worker",
        "taskenv": task["id"],
        "name": "worker",
        "state": "stopped",
        "directory": str(directory),
    }
    registry.put("service", service)
    projects = registry.all("project")
    checkout = repo.rename(repo.parent / "moved") if missing else repo

    preview = worktrees.forget(registry, task, yes=False)
    assert preview["state"] == ("missing" if missing else "present")
    assert preview["services"] == [service] and "forgotten" not in preview
    assert "does not stop services" in preview["warning"]
    assert registry.get("taskenv", task["id"]) == task
    with registry.lock(task["id"]):
        with pytest.raises(ManagementError) as error:
            worktrees.forget(registry, task, yes=True)
        assert error.value.code == "busy"
    assert registry.get("taskenv", task["id"]) == task

    result = worktrees.forget(registry, task, yes=True)
    assert result["forgotten"] is True and result["id"] == task["id"]
    assert registry.all("taskenv") == []
    assert registry.all("project") == projects
    assert registry.all("service") == [service]
    assert SQLiteSecrets(registry).get("secret:shared") == "fixture-secret"
    assert (checkout / "README.md").read_text() == "fixture\n"


def test_create_attach_identity_and_merge(registry: Registry, repo: Path) -> None:
    main = register(registry, repo)
    a = worktrees.create(registry, "fixture", "initial", "feature-a")
    b = worktrees.create(registry, "fixture", "HEAD", "feature-b")
    assert a["ports"] != b["ports"]
    assert a["id"] != b["id"]
    assert worktrees.attach(registry, "fixture", Path(a["path"]))["id"] == a["id"]
    assert worktrees.resolve(registry, str(Path(a["path"]) / ".lodex"))["id"] == a["id"]
    second = Registry(registry.root)
    try:
        assert worktrees.resolve(second, a["id"])["path"] == a["path"]
    finally:
        second.close()
    (Path(a["path"]) / "change.txt").write_text("change")
    worktrees.git(Path(a["path"]), "add", "change.txt")
    worktrees.git(Path(a["path"]), "commit", "-qm", "change")
    worktrees.git(repo, "merge", "--ff-only", "feature-a")
    assert (repo / "change.txt").exists()
    with pytest.raises(ManagementError, match="external or main"):
        worktrees.remove(registry, main, yes=True, force=True)
    external = repo.parent / "detached"
    worktrees.git(repo, "worktree", "add", "--detach", str(external), "initial")
    detached = worktrees.attach(registry, "fixture", external)
    assert not detached["owned"]
    assert worktrees.git(external, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    with pytest.raises(ManagementError, match="external or main"):
        worktrees.remove(registry, detached, yes=True, force=True)


@pytest.mark.parametrize("length", [56, 57, 64])
def test_create_worktree_with_long_project_name(
    registry: Registry, repo: Path, length: int
) -> None:
    label = "p" * length
    worktrees.project_add(registry, label, repo, None)
    task = worktrees.create(registry, label, "HEAD", "feature/long-project")
    assert task["project"] == label
    assert Path(task["path"]).parent == registry.root / "projects" / label
    assert worktrees.inspect(registry, task)["state"] == "present"
    assert worktrees.attach(registry, label, Path(task["path"]))["id"] == task["id"]


def test_same_remote_different_clone_and_replacement(registry: Registry, repo: Path) -> None:
    original = register(registry, repo)
    worktrees.git(repo, "remote", "add", "origin", "https://example.invalid/shared.git")
    clone = repo.parent / "clone"
    worktrees.git(repo.parent, "clone", str(repo), str(clone))
    worktrees.git(clone, "remote", "set-url", "origin", "https://example.invalid/shared.git")
    worktrees.project_add(registry, "clone", clone, repo / project_config.CONFIG)
    with pytest.raises(ManagementError, match="different local"):
        worktrees.attach(registry, "fixture", clone)
    repo.rename(repo.with_name("moved"))
    assert worktrees.inspect(registry, original)["state"] == "missing"
    worktrees.git(clone.parent, "clone", str(clone), str(repo))
    assert worktrees.resolve(registry, str(repo))["id"] == original["id"]
    assert worktrees.inspect(registry, original)["state"] == "identity_changed"


@pytest.mark.parametrize("tracked", ["tracked", "untracked", "ignored"])
def test_config_copy_contract(registry: Registry, repo: Path, tracked: str) -> None:
    if tracked == "tracked":
        worktrees.git(repo, "add", str(project_config.CONFIG))
        worktrees.git(repo, "commit", "-qm", "config")
    elif tracked == "ignored":
        (repo / ".git" / "info" / "exclude").write_text(".lodex/\n")
    (repo / ".env").write_text("DO_NOT_COPY=1")
    (repo / "helper.py").write_text("pass")
    register(registry, repo)
    before = worktrees.git(repo, "status", "--porcelain")
    a = worktrees.create(registry, "fixture", "initial", "a")
    b = worktrees.create(registry, "fixture", "HEAD", "b")
    root = Path(a["path"])
    assert not (root / ".env").exists() and not (root / "helper.py").exists()
    assert worktrees.git(repo, "status", "--porcelain") == before
    (root / project_config.CONFIG).write_text('schema_version = 1\n[env]\nVALUE="A"\n')
    worktrees.attach(registry, "fixture", root)
    assert "VALUE" not in (Path(b["path"]) / project_config.CONFIG).read_text()
    assert project_config.load(root / project_config.CONFIG)["env"] == {"VALUE": "A"}
    (root / project_config.CONFIG).write_text("broken = [")
    with pytest.raises(ManagementError):
        worktrees.attach(registry, "fixture", root)
    assert (root / project_config.CONFIG).read_text() == "broken = ["
    (root / project_config.CONFIG).unlink()
    assert worktrees.inspect(registry, a)["config_status"] == "config_unavailable"
    assert not (root / project_config.CONFIG).exists()
    (repo / project_config.CONFIG).unlink()
    with pytest.raises(ManagementError):
        worktrees.attach(registry, "fixture", root)


@pytest.mark.parametrize("initialize", [False, True])
def test_parallel_config_publication(repo: Path, tmp_path: Path, initialize: bool) -> None:
    destination = tmp_path / "destination"
    source = None if initialize else repo / project_config.CONFIG
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: project_config.supply(destination, source), range(2)))
    assert {r["method"] for r in results} == {
        "initialized" if initialize else "copied",
        "existing",
    }
    expected = project_config.SKELETON.encode() if source is None else source.read_bytes()
    assert (destination / project_config.CONFIG).read_bytes() == expected


def test_remove_git_protection(registry: Registry, repo: Path) -> None:
    register(registry, repo)
    task = worktrees.create(registry, "fixture", "initial", "remove-test")
    root = Path(task["path"])
    (root / "README.md").write_text("dirty")
    preview = worktrees.remove(registry, task, yes=False, force=False)
    assert "README.md" in preview["git_status"] and "ignored" in preview["warning"]
    with pytest.raises(ManagementError):
        worktrees.remove(registry, task, yes=True, force=False)
    worktrees.remove(registry, task, yes=True, force=True)
    assert not root.exists()
    assert worktrees.inspect(registry, task)["state"] == "missing"


def test_storage_collision_and_migration_failure(registry: Registry, tmp_path: Path) -> None:
    from lodex_core.history.storage import Storage, StorageCompatibilityError

    with pytest.raises(StorageCompatibilityError, match="non-history"):
        Storage.rebuild(registry.path, dimension=3)
    assert registry.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    other = tmp_path / "history"
    other.mkdir()
    with Storage(other / "management.db", dimension=3):
        pass
    with pytest.raises(ManagementError, match="non-management"):
        Registry(other)
    registry.db.execute("PRAGMA user_version=999")
    with pytest.raises(ManagementError, match="version"):
        Registry(registry.root)
    assert registry.db.execute("PRAGMA user_version").fetchone()[0] == 999


def test_schema_scripts_and_lock(registry: Registry, repo: Path) -> None:
    task = register(registry, repo)
    with registry.lock(task["id"]), pytest.raises(ManagementError, match="Another operation"):
        with registry.lock(task["id"]):
            pass
    with pytest.raises(ManagementError, match="Missing repo script"):
        project_config.check_command(repo, {"scripts": ["missing.py"]}, {"tools": []})
    (repo / project_config.CONFIG).write_text("schema_version=99\n")
    with pytest.raises(ManagementError):
        project_config.load(repo / project_config.CONFIG)


def test_stale_task_input_preserves_other_port_assignments(registry: Registry, repo: Path) -> None:
    from lodex_core.management import settings

    (repo / project_config.CONFIG).write_text("schema_version=1\n[ports]\nA=0\nB=0\n")
    task = register(registry, repo)
    stale = dict(task)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        new_port = probe.getsockname()[1]
    assert new_port not in task["ports"].values()
    settings.set_port(registry, task, "A", str(new_port))
    settings.set_port(registry, stale, "B", str(task["ports"]["B"]))
    assert registry.get("taskenv", task["id"])["ports"] == {
        "A": new_port,
        "B": task["ports"]["B"],
    }


def test_initial_migration_rolls_back_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connect = sqlite3.connect

    class FailMigration(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            if sql == f"PRAGMA user_version={SCHEMA_VERSION}":
                raise sqlite3.OperationalError("injected migration failure")
            return super().execute(sql, parameters)

    def failing_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return connect(*args, **kwargs, factory=FailMigration)

    root = tmp_path / "failed-registry"
    monkeypatch.setattr(sqlite3, "connect", failing_connect)
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        Registry(root)
    with connect(root / "management.db") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
        assert db.execute("PRAGMA application_id").fetchone()[0] == 0
        assert not db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    monkeypatch.setattr(sqlite3, "connect", connect)
    recovered = Registry(root)
    recovered.close()
