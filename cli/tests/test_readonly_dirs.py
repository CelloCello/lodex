from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lodex_cli import worker_policy
from lodex_cli.main import app
from lodex_core.management import operations, worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.project_config import CONFIG, load
from lodex_core.management.store import Registry


@pytest.fixture
def shares(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    store = Registry(tmp_path / "manager")
    config = 'schema_version=1\nreadonly_dirs=["_plans"]\n[commands.prepare]\nargv=["true"]\n'
    (repo / CONFIG).write_text(config)
    worktrees.project_add(store, "demo", repo, None)
    legacy = worktrees.attach(store, "demo", repo)
    del legacy["workspace_root"]  # Source registered before the workspace layout migration.
    store.put("taskenv", legacy)
    home = tmp_path / "codex"
    home.mkdir()
    (home / "fixture.config.toml").write_text('approval_policy="never"\n')
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("LODEX_HOME", str(store.root))
    task = worktrees.create(store, "demo", "HEAD", "readonly-a")
    try:
        yield store, task
    finally:
        store.close()


def test_share_conflicts_source_authority_and_retry(repo: Path, shares: Any) -> None:
    store, task = shares
    link = Path(task["path"]) / "_plans"
    with pytest.raises(ManagementError, match="Cannot resolve"):
        operations.run(store, task, "prepare")
    (repo / "_plans").mkdir()
    link.mkdir()
    with pytest.raises(ManagementError, match="conflicting"):
        operations.run(store, task, "prepare")
    assert link.is_dir() and not link.is_symlink()
    link.rmdir()
    for _ in range(2):
        prepared = operations.run(store, task, "prepare")
        assert prepared["handoff"]["readonly_dirs"] == {"_plans": str(repo / "_plans")}
    (repo / CONFIG).write_text("schema_version=1\n")
    assert "readonly_dirs" not in operations.run(store, task, "prepare")["handoff"]
    assert not link.is_symlink()
    (Path(task["path"]) / CONFIG).write_text(
        'schema_version=1\n[commands.prepare]\nargv=["true"]\n'
    )
    assert "readonly_dirs" not in operations.run(store, task, "prepare")["handoff"]
    assert not link.is_symlink()


@pytest.mark.parametrize("invalid", ["_plans", ["."], ["../x"], ["/x"], ["a/.git"], ["a", "a/b"]])
def test_invalid_names(repo: Path, invalid: Any) -> None:
    (repo / CONFIG).write_text("schema_version=1\nreadonly_dirs=" + json.dumps(invalid))
    with pytest.raises(ManagementError, match="readonly_dirs"):
        load(repo / CONFIG)


def test_external_source_symlink_and_saved_policy(shares: Any, repo: Path, tmp_path: Path) -> None:
    store, task = shares
    external = tmp_path / "dedicated-plans"
    external.mkdir()
    (repo / "_plans").symlink_to(external)
    prepared = operations.run(store, task, "prepare")
    args = dict(prepare_operation=prepared["id"], cache=tmp_path / "uv", profile="fixture")
    if shutil.which("codex") is None:
        pytest.skip("Codex required to render policy")
    policy = worker_policy.render(store, task, **args)
    assert policy["filesystem"][str(external)] == "read"
    # Revocation in the trusted source also applies to a previously issued policy.
    original_recipe = (repo / CONFIG).read_bytes()
    (repo / CONFIG).write_text("schema_version=1\n")
    with pytest.raises(ManagementError, match="Shared directories changed"):
        worker_policy.read(store, task, Path(policy["policy_file"]))
    (repo / CONFIG).write_bytes(original_recipe)
    (repo / "_plans").unlink()
    (repo / "_plans").symlink_to(store.root)
    with pytest.raises(ManagementError, match="Unsafe"):
        worker_policy.read(store, task, Path(policy["policy_file"]))

    pattern = tmp_path / "notes-*"
    pattern.mkdir()
    (repo / "_plans").unlink()
    (repo / "_plans").symlink_to(pattern)
    with pytest.raises(ManagementError, match="Unsafe"):
        operations.run(store, task, "prepare")


def test_peer_removal_preserves_shared_source_and_surviving_link(shares: Any, repo: Path) -> None:
    store, a = shares
    original = repo / "_plans" / "notes"
    original.parent.mkdir()
    original.write_text("v1")
    b = worktrees.create(store, "demo", "HEAD", "readonly-b")
    for task in (a, b):
        operations.run(store, task, "prepare")
        assert (Path(task["path"]) / "_plans/notes").read_text() == "v1"
    worktrees.remove(store, a, yes=True, force=True)
    worktrees.forget(store, a, yes=True)
    assert original.read_text() == "v1"
    original.write_text("v2")
    assert (Path(b["path"]) / "_plans/notes").read_text() == "v2"


@pytest.mark.skipif(
    os.environ.get("LODEX_TEST_SANDBOX") != "1" or sys.platform != "darwin",
    reason="Real macOS worker sandbox",
)
def test_registered_source_readonly_in_sandbox(shares: Any, repo: Path, tmp_path: Path) -> None:
    store, task = shares
    original = repo / "_plans" / "example"
    original.parent.mkdir()
    original.write_text("one")
    prepared = operations.run(store, task, "prepare")
    policy = worker_policy.render(
        store, task, prepare_operation=prepared["id"], cache=tmp_path / "cache", profile="fixture"
    )
    original.write_text("two")
    program = """from pathlib import Path
import sys
p = Path('_plans/example')
assert p.read_text() == 'two'
for path, mode in [(p, 'a'), (Path(sys.argv[1]), 'a'), (Path(sys.argv[2]), 'r')]:
    try: path.open(mode).close()
    except PermissionError: continue
    raise AssertionError((path, mode))
"""
    result = subprocess.run(
        [
            *policy["sandbox_argv"],
            "--",
            sys.executable,
            "-c",
            program,
            str(original),
            str(repo / "README.md"),
        ],
        env={**os.environ, **policy["launch_env"]},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def recipe(root: Path, names: list[str], cleanup: list[str] | None = None) -> None:
    (root / CONFIG).write_text(
        "schema_version=1\nreadonly_dirs="
        + json.dumps(names)
        + '\n[commands.prepare]\nargv=["true"]\n[commands.cleanup]\nargv='
        + json.dumps(cleanup or ["true"])
        + "\n"
    )


def test_prepare_only_retires_its_own_links(shares: Any, repo: Path) -> None:
    store, task = shares
    root = Path(task["path"])
    names = ["owned", "borrowed", "replaced", "same-target"]
    for name in names:
        (repo / name).mkdir()
    for checkout in (repo, root):
        recipe(checkout, names)
    (root / "borrowed").symlink_to(repo / "borrowed")
    operations.run(store, task, "prepare")
    (root / "replaced").unlink()
    (root / "replaced").write_text("my file")
    # Keep the old inode alive so this is unambiguously a different symlink.
    (root / "same-target").rename(root / "user-backup")
    (root / "same-target").symlink_to(repo / "same-target")
    recipe(root, [])
    operations.run(store, task, "prepare")
    assert not (root / "owned").is_symlink()
    assert (root / "borrowed").readlink() == repo / "borrowed"
    assert (root / "replaced").read_text() == "my file"
    assert (root / "same-target").readlink() == repo / "same-target"
    assert not store.get("taskenv", task["id"]).get("owned_readonly_links")
    assert all((repo / name).is_dir() for name in names)


@pytest.mark.parametrize("failure", ["conflict", "publish"])
def test_failed_batch_restores_owned_links_and_new_parents(
    shares: Any, repo: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    store, task = shares
    root = Path(task["path"])
    (repo / "_plans").mkdir()
    operations.run(store, task, "prepare")
    old = (root / "_plans").lstat()
    names = ["nested/new", "z"]
    for name in names:
        (repo / name).mkdir(parents=True)
    for checkout in (repo, root):
        recipe(checkout, names)
    if failure == "conflict":
        (root / "z").write_text("mine")
    else:
        symlink = os.symlink

        def fail_last(src: str, dst: str, *, dir_fd: int) -> None:
            if dst == "z":
                raise OSError("injected publication failure")
            symlink(src, dst, dir_fd=dir_fd)

        monkeypatch.setattr(os, "symlink", fail_last)
    with pytest.raises(ManagementError):
        operations.run(store, task, "prepare")
    assert (root / "_plans").lstat().st_ino == old.st_ino
    assert (root / "_plans").readlink() == repo / "_plans"
    assert not (root / "nested").exists()
    assert not list(root.glob(".lodex-link-*"))
    assert any(
        op["state"] == "failed" and op.get("error") == "readonly_dirs"
        for op in store.all("operation")
    )
    if failure == "conflict":
        assert (root / "z").read_text() == "mine"
        (root / "z").unlink()
    if failure == "publish":
        monkeypatch.setattr(os, "symlink", symlink)
    operations.run(store, task, "prepare")
    assert not (root / "_plans").is_symlink()
    assert all((root / name).readlink() == repo / name for name in names)


@pytest.mark.skipif(
    os.environ.get("LODEX_TEST_SANDBOX") != "1" or sys.platform != "darwin",
    reason="Real macOS restricted cleanup",
)
@pytest.mark.parametrize(
    "change", ["source-revoked", "source-removed", "task-revoked", "retarget", "added-main"]
)
def test_cleanup_applies_saved_and_current_limits(
    shares: Any, repo: Path, tmp_path: Path, change: str
) -> None:
    store, task = shares
    original = repo / "_plans"
    if change == "added-main":
        task = worktrees.resolve(store, str(repo))
        original.mkdir()
        recipe(repo, [])
    else:
        external = tmp_path / "external-plans"
        external.mkdir()
        original.symlink_to(external)
    root = Path(task["path"])
    target = original.resolve() / "draft"
    target.write_text("original")
    prepared = operations.run(store, task, "prepare")
    policy = worker_policy.render(
        store, task, prepare_operation=prepared["id"], cache=tmp_path / "cache", profile="fixture"
    )
    path = Path(policy["policy_file"])
    snapshot = path.read_bytes()
    test_paths = [(str(target), "a" if change == "added-main" else "r")]
    if change == "source-revoked":
        recipe(repo, [])
    if change == "source-removed":
        (repo / CONFIG).unlink()
    if change == "retarget":
        original.unlink()
        new = repo / "private"
        new.mkdir()
        (new / "draft").write_text("new")
        original.symlink_to(new)
        test_paths.append(
            (str(new / "draft"), "r")
        )  # Denied by the original legacy-source boundary.
    script = """from pathlib import Path
import sys, json
for path, mode in json.loads(sys.argv[1]):
    try:
        with open(path, mode): pass
    except PermissionError: continue
    raise AssertionError((path, mode))
Path("task-data").unlink()
"""
    names = [] if change == "task-revoked" else ["_plans"]
    recipe(root, names, [sys.executable, "-c", script, json.dumps(test_paths)])
    (root / "task-data").touch()
    result = CliRunner().invoke(
        app, ["cleanup", "--target", task["id"], "--worker-policy", str(path), "--json"]
    )
    data = json.loads(result.stdout)
    assert result.exit_code == 0, data if "result" not in data else operations.logs(data["result"])
    assert not (root / "task-data").exists()
    assert target.read_text() == "original" and path.read_bytes() == snapshot


def test_retarget_refreshes_only_after_worker_exit(shares: Any, repo: Path, tmp_path: Path) -> None:
    from lodex_core.management.worker_sessions import session_lock

    store, task = shares
    root = Path(task["path"])
    for name in ("first", "second"):
        (tmp_path / name).mkdir()
    source = repo / "_plans"
    source.symlink_to(tmp_path / "first")
    initial = operations.run(store, task, "prepare")
    if shutil.which("codex") is None:
        pytest.skip("Codex required to render a policy")
    old = worker_policy.render(
        store, task, prepare_operation=initial["id"], profile="fixture", cache=tmp_path / "cache"
    )
    path = Path(old["policy_file"])
    with session_lock(store.root, task["id"]):
        assert operations.run(store, task, "prepare")["state"] == "succeeded"
        source.unlink()
        source.symlink_to(tmp_path / "second")
        with pytest.raises(ManagementError) as active:
            operations.run(store, task, "prepare")
        assert active.value.code == "worker_active"
        assert (root / "_plans").readlink() == tmp_path / "first"
    with pytest.raises(ManagementError):
        worker_policy.read(store, task, path)
    renewed = operations.run(store, task, "prepare")
    assert (root / "_plans").readlink() == tmp_path / "second"
    with pytest.raises(ManagementError, match="Shared directories changed"):
        worker_policy.read(store, task, path)
    new = worker_policy.render(
        store, task, prepare_operation=renewed["id"], profile="fixture", cache=tmp_path / "cache"
    )
    assert worker_policy.read(store, task, Path(new["policy_file"]))["id"] == new["id"]
