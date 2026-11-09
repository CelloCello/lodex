from __future__ import annotations

import json
from pathlib import Path

import pytest

from lodex_cli import main as cli
from lodex_core.management import worktrees
from lodex_core.management.store import Registry

from .support.management import register


def test_attach_rebind_cli_previews_and_requires_confirmation(
    registry: Registry,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task = register(registry, repo)
    task["git_dir"] += "-old"
    registry.put("taskenv", task)
    monkeypatch.setenv("LODEX_HOME", str(registry.root))
    args = ["worktree", "attach", "fixture", str(repo)]
    assert cli.main([*args, "--json"]) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "identity_changed" and error["details"]["rebind"]
    assert cli.main([*args, "--rebind", "--json"]) == 0
    assert not json.loads(capsys.readouterr().out)["result"]["rebound"]
    assert registry.get("taskenv", task["id"]) == task
    assert cli.main([*args, "--rebind", "--yes", "--json"]) == 0
    rebound = json.loads(capsys.readouterr().out)["result"]
    assert rebound["rebound"] and rebound["id"] == task["id"]
    assert rebound["prepare_required"] and not rebound["owned"]
    assert worktrees.state(rebound) == "present"
    assert cli.main([*args, "--yes", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_input"


def test_repair_identity_draft_command_is_not_available(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["project", "repair-identity", "fixture", "--json"]) == 2
    capsys.readouterr()


def test_rebind_cli_requires_each_unknown_operation_acknowledgement(
    registry: Registry,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task = register(registry, repo)
    registry.put("operation", {"id": "old-op", "taskenv": task["id"], "state": "unknown"})
    monkeypatch.setenv("LODEX_HOME", str(registry.root))
    args = ["worktree", "attach", "fixture", str(repo), "--rebind"]
    assert cli.main([*args, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["required_acknowledgements"] == ["old-op"]
    assert cli.main([*args, "--yes", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "unresolved_operations"
    assert cli.main([*args, "--yes", "--acknowledge-operation", "old-op", "--json"]) == 0
    bound = json.loads(capsys.readouterr().out)["result"]
    assert bound["rebound"] and "old-op" in bound["rebind_acknowledgements"]
    assert registry.get("operation", "old-op")["state"] == "unknown"
