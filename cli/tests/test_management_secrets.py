from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from lodex_cli import main as cli
from lodex_core.management import worktrees
from lodex_core.management.project_config import CONFIG
from lodex_core.management.secrets import SQLiteSecrets
from lodex_core.management.store import Registry

from .support.management import register
from .support.operations import recipe


def test_secret_cli_across_callers_and_shared_reference(registry: Registry, repo: Path) -> None:
    recipe(repo)
    a = register(registry, repo)
    b = worktrees.create(registry, "fixture", "HEAD", "secret-b")
    values = ("fixture-secret-CLI-a", "fixture-secret-CLI-b")

    def call(*args: str, target: str = a["id"], value: str | None = None, ok: bool = True) -> Any:
        command = [sys.executable, "-m", "lodex_cli.main", *args, "--json"]
        if args[0] != "secret":
            command += ["--target", target]
        result = subprocess.run(
            command,
            env={**os.environ, "LODEX_HOME": str(registry.root)},
            input=value,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert (result.returncode == 0) is ok, result.stdout + result.stderr
        assert all(secret not in result.stdout + result.stderr for secret in values)
        # Check all public records after each call, before cleanup can erase a leak.
        records = registry.db.execute("SELECT data FROM records").fetchall()
        assert all(secret not in row[0] for row in records for secret in values)
        output: dict[str, Any] = json.loads(result.stdout)
        return output["result" if ok else "error"]

    assert call("prepare", ok=False)["code"] == "missing_secret"
    call("secret", "set", "fixture", "--stdin", value=values[0] + "\n")
    assert call("secret", "list") == ["fixture"]
    assert call("env", "show")["secret_refs"] == {"TOKEN": "secret:fixture"}
    call("context")
    assert call("prepare", target=b["id"])["state"] == "succeeded"
    call("secret", "set", "fixture", "--stdin", value=values[1] + "\n")
    (repo / ".gitignore").write_text(".env\n")
    (Path(b["path"]) / ".gitignore").write_text(".env\n")
    call("env", "export")
    call("env", "export", target=b["id"])
    assert values[1] in (repo / ".env").read_text()
    assert values[1] in (Path(b["path"]) / ".env").read_text()
    b_config = Path(b["path"]) / CONFIG
    b_config.write_text(b_config.read_text().replace("secret:fixture", "secret:separate"))
    call("secret", "set", "separate", "--stdin", value=values[0] + "\n")
    call("env", "export", target=b["id"])
    assert values[0] in (Path(b["path"]) / ".env").read_text()
    assert call("env", "show")["secret_refs"] == {"TOKEN": "secret:fixture"}
    assert call("cleanup")["state"] == "succeeded"
    provider = SQLiteSecrets(registry)
    assert provider.get("secret:fixture") == values[1]
    call("secret", "remove", "fixture")  # Preview leaves the shared value in place.
    assert provider.get("secret:fixture") == values[1]
    call("secret", "remove", "fixture", "--yes")
    assert call("prepare", ok=False)["code"] == "missing_secret"
    assert call("prepare", target=b["id"])["state"] == "succeeded"
    b_config.write_text(b_config.read_text().replace("secret:separate", "secret:fixture"))
    assert call("prepare", target=b["id"], ok=False)["code"] == "missing_secret"
    call("worktree", "forget", "--yes", target=b["id"])
    assert provider.get("secret:separate") == values[0]
    assert call("secret", "list") == ["separate"]


def test_secret_cli_without_project_config_or_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "standalone"
    monkeypatch.setenv("LODEX_HOME", str(root))

    def missing_cwd() -> Path:
        raise FileNotFoundError("deleted working directory")

    monkeypatch.setattr(Path, "cwd", missing_cwd)
    assert cli.main(["secret", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == []
    assert not root.exists()
    monkeypatch.setattr(sys, "stdin", io.StringIO("standalone-fixture-value\n"))
    assert cli.main(["secret", "set", "app-token", "--stdin", "--json"]) == 0
    assert "standalone-fixture-value" not in capsys.readouterr().out
    assert cli.main(["secret", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == ["app-token"]
    db = Registry(root, read_only=True)
    try:
        assert SQLiteSecrets(db).get("secret:app-token") == "standalone-fixture-value"
        assert db.db.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
    finally:
        db.close()
    assert cli.main(["secret", "remove", "app-token", "--yes", "--json"]) == 0
    capsys.readouterr()
    assert cli.main(["secret", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == []


@pytest.mark.parametrize(
    "args",
    [
        ["env", "set", "KEY", "value"],
        ["env", "unset", "KEY"],
        ["secret", "ref", "KEY", "secret:name"],
        ["secret", "unref", "KEY"],
    ],
)
def test_removed_override_commands_reject_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
) -> None:
    root = tmp_path / "unused"
    monkeypatch.setenv("LODEX_HOME", str(root))
    assert cli.main([*args, "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "usage"
    assert not root.exists()
