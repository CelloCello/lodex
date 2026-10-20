from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lodex_cli import __version__
from lodex_cli.main import app, main


@pytest.mark.parametrize(
    "args,management",
    [
        (["project", "--json"], True),
        (["project", "add", "fixture", "--json"], True),
        (["worktree", "create", "fixture", "--ref", "HEAD", "--json"], True),
        (["env", "show", "--unknown", "--json"], True),
        (["secret", "set", "fixture", "--target", "unused", "--json"], True),
        (["search", "--json"], False),
        (["search", "query", "--kind", "invalid", "--json"], False),
        (["show", "chunk", "--context", "invalid", "--json"], False),
        (["unknown", "--json"], False),
    ],
)
def test_usage_errors_are_json_without_initializing_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, args: list[str], management: bool
) -> None:
    home = tmp_path / "unused"
    monkeypatch.setenv("LODEX_HOME", str(home))
    monkeypatch.setenv("LODEX_CONFIG", str(tmp_path / "missing.toml"))
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2, result.output
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    if management:
        assert payload["error"]["code"] == "usage"
        assert payload["error"]["message"]
    else:
        assert payload["command"] == args[0]
        assert isinstance(payload["error"], str) and payload["error"]
    assert not home.exists()


@pytest.mark.parametrize("args", [["project", "--json", "list"], ["project", "list", "--json"]])
def test_group_and_leaf_json_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, args: list[str]
) -> None:
    monkeypatch.setenv("LODEX_HOME", str(tmp_path / "unused"))
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert result.stdout == '{"ok": true, "result": []}\n'


def test_help_tree_is_available_without_loading_runtime_or_state(tmp_path: Path) -> None:
    # A fresh interpreter catches eager imports that the ordinary test process hides.
    script = """
import sys
from typer.core import TyperGroup
from typer.main import get_command
from typer.testing import CliRunner
from lodex_cli.main import app

runner = CliRunner()
def check_help(command, path):
    result = runner.invoke(app, [*path, '--help'])
    assert result.exit_code == 0, (path, result.output)
    assert 'Usage:' in result.stdout and not result.stderr, path
    if path == ['console']:
        assert 'lodex[console]' in result.stdout, result.stdout
    if isinstance(command, TyperGroup):
        for name, child in command.commands.items():
            check_help(child, [*path, name])

check_help(get_command(app), [])
for args in ([], ['-h'], ['env', 'export', '-h']):
    result = runner.invoke(app, args)
    assert result.exit_code == 0 and 'Usage:' in result.stdout, result.output
assert not any(name in sys.modules for name in (
    'lodex_core.history.embedding', 'lodex_core.history.storage', 'lodex_core.history.queries',
    'sqlite_vec', 'ollama',
    'lodex_core.management.operations', 'lodex_core.management.services',
))
"""
    home = tmp_path / "unused"
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "LODEX_HOME": str(home), "LODEX_CONFIG": str(tmp_path / "missing")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert not home.exists()


def test_version_and_main_return_code(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out == f"lodex {__version__}\n"
    assert main(["project", "add", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "usage"


def test_missing_cwd_fails_before_opening_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "unused"
    monkeypatch.setenv("LODEX_HOME", str(home))

    def missing() -> Path:
        raise FileNotFoundError("removed directory")

    monkeypatch.setattr(Path, "cwd", missing)
    result = CliRunner().invoke(app, ["prepare", "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)["error"]["code"] == "missing_cwd"
    assert not home.exists()


def test_clirunner_propagates_failed_repository_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo: Path
) -> None:
    monkeypatch.setenv("LODEX_HOME", str(tmp_path / "manager"))
    (repo / ".lodex/project.toml").write_text(
        "schema_version = 1\n[commands.verify]\n"
        f"argv = {json.dumps([sys.executable, '-c', 'raise SystemExit(7)'])}\n"
    )
    runner = CliRunner()
    for args in (
        ["project", "add", "fixture", str(repo), "--json"],
        ["worktree", "attach", "fixture", str(repo), "--json"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["run", "verify", "--target", str(repo), "--json"])
    assert result.exit_code == 1, result.output
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["result"]["state"] == "failed"
    assert payload["result"]["exit_code"] == 7
