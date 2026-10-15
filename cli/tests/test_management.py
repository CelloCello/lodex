from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lodex_cli import main as cli
from lodex_core.management import project_config, worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.store import Registry

from .support.management import register


@pytest.mark.parametrize("linked", [False, True])
def test_resolve_respects_nested_checkout_boundary(
    registry: Registry, repo: Path, linked: bool
) -> None:
    outer = register(registry, repo)
    nested = repo / "nested"
    if linked:
        worktrees.git(repo, "worktree", "add", "--detach", str(nested), "HEAD")
    else:
        nested.mkdir()
        worktrees.git(nested, "init", "-q")
    subdir = nested / "src"
    subdir.mkdir()
    for path in (nested, subdir, subdir / "not-created"):
        with pytest.raises(ManagementError, match="No registered taskenv"):
            worktrees.resolve(registry, str(path))
    for command in (("context",), ("prepare",), ("cleanup",), ("worktree", "remove")):
        result = subprocess.run(
            [sys.executable, "-m", "lodex_cli.main", *command, "--json"],
            cwd=subdir,
            env={**os.environ, "LODEX_HOME": str(registry.root)},
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode != 0
        assert json.loads(result.stdout)["error"]["code"] == "not_found"
    project_config.supply(nested, repo / project_config.CONFIG)
    if not linked:
        worktrees.project_add(registry, "nested", nested, None)
    inner = worktrees.attach(registry, "fixture" if linked else "nested", nested)
    assert worktrees.resolve(registry, str(subdir))["id"] == inner["id"]
    assert worktrees.resolve(registry, str(repo / ".lodex"))["id"] == outer["id"]
    nested.rename(repo / "moved-nested")
    assert worktrees.resolve(registry, str(subdir))["id"] == inner["id"]
    assert worktrees.resolve(registry, inner["id"])["id"] == inner["id"]
    assert worktrees.inspect(registry, inner)["state"] == "missing"


def test_cli_independent_imports_and_config(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.toml"
    invalid.write_text("[embedding]\ndimension = -1\n")
    env = {**os.environ, "LODEX_HOME": str(tmp_path / "cli"), "LODEX_CONFIG": str(invalid)}
    script = (
        "import sys; from lodex_cli.main import main; "
        "assert main(['project','list','--json']) == 0; "
        "assert not any(x in sys.modules for x in "
        "['lodex_core.history.embedding','lodex_core.history.storage','sqlite_vec','ollama','lodex_core.history.queries'])"
    )
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"]


def test_context_does_not_write_and_partial_create_is_recoverable(
    registry: Registry,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task = register(registry, repo)
    monkeypatch.setenv("LODEX_HOME", str(registry.root))
    (repo / project_config.CONFIG).unlink()
    before = {
        p: (p.stat().st_mtime_ns, p.read_bytes()) for p in registry.root.rglob("*") if p.is_file()
    }
    assert cli.main(["context", "--target", task["id"], "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["config_status"] == "config_unavailable"
    after = {
        p: (p.stat().st_mtime_ns, p.read_bytes()) for p in registry.root.rglob("*") if p.is_file()
    }
    assert before == after
    with pytest.raises(ManagementError, match="attach after fixing"):
        worktrees.create(registry, "fixture", "HEAD", "partial")
    partial = next(t for t in registry.all("taskenv") if t["id"] != task["id"])
    assert partial["owned"] and partial["setup_error"]
    (repo / project_config.CONFIG).write_text("schema_version=1\n")
    restored = worktrees.attach(registry, "fixture", Path(partial["path"]))
    assert restored["id"] == partial["id"] and "setup_error" not in restored
    worktrees.remove(registry, restored, yes=True, force=True)


def test_create_registry_contention_has_no_git_side_effects(registry: Registry, repo: Path) -> None:
    register(registry, repo)
    before = worktrees.git(repo, "worktree", "list", "--porcelain")
    records = registry.all("taskenv")
    with registry.lock("registry"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "lodex_cli.main",
                "worktree",
                "create",
                "fixture",
                "--ref",
                "HEAD",
                "--branch",
                "contended",
                "--json",
            ],
            env={**os.environ, "LODEX_HOME": str(registry.root)},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 1
        assert json.loads(result.stdout)["error"]["code"] == "busy"
    assert worktrees.git(repo, "worktree", "list", "--porcelain") == before
    assert not worktrees.git(repo, "branch", "--list", "contended")
    assert registry.all("taskenv") == records
    task = worktrees.create(registry, "fixture", "HEAD", "contended")
    assert task["owned"]
    assert registry.get("taskenv", task["id"])["path"] == task["path"]


def test_cli_deleted_cwd_explicit_targets_and_targetless_commands(
    registry: Registry, repo: Path, tmp_path: Path
) -> None:
    task = register(registry, repo)
    cwd = tmp_path / "deleted-cwd"
    cwd.mkdir()
    script = (
        "import contextlib,io,json,os,sys\n"
        "from lodex_cli.main import main\n"
        "os.chdir(sys.argv[1]); os.rmdir(sys.argv[1])\n"
        "cases=[['worktree','inspect','--target',sys.argv[2]],"
        "['context','--target',sys.argv[3]],['service','list','--target',sys.argv[2]],"
        "['project','list'],['worktree','inspect']]\n"
        "for args in cases:\n"
        "    output=io.StringIO()\n"
        "    with contextlib.redirect_stdout(output): code=main([*args,'--json'])\n"
        "    print(json.dumps({'code':code,'response':json.loads(output.getvalue())}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(cwd), task["id"], str(repo)],
        env={**os.environ, "LODEX_HOME": str(registry.root)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    outputs = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(outputs) == 5
    assert all(item["code"] == 0 and item["response"]["ok"] for item in outputs[:4])
    assert outputs[0]["response"]["result"]["id"] == task["id"]
    assert outputs[4]["code"] == 1
    assert outputs[4]["response"]["error"]["code"] == "missing_cwd"
    assert "--target" in outputs[4]["response"]["error"]["message"]
    # Omitting --target in an ordinary subdirectory still resolves that checkout.
    result = subprocess.run(
        [sys.executable, "-m", "lodex_cli.main", "context", "--json"],
        cwd=repo / ".lodex",
        env={**os.environ, "LODEX_HOME": str(registry.root)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result"]["id"] == task["id"]


@pytest.mark.parametrize(
    "ready_port", ['["PORT"]', '{name="PORT"}', "42", "true", '""', '"ABSENT"']
)
def test_invalid_ready_port_returns_json_config_error(
    repo: Path, tmp_path: Path, ready_port: str
) -> None:
    (repo / project_config.CONFIG).write_text(
        'schema_version=1\n[ports]\nPORT=0\n[services.web]\nargv=["unused"]\n'
        f"ready_port={ready_port}\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "lodex_cli.main", "project", "add", "fixture", str(repo), "--json"],
        env={**os.environ, "LODEX_HOME": str(tmp_path / "invalid-config")},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert result.stderr == ""
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "invalid_config"
    assert "ready_port" in error["message"]
