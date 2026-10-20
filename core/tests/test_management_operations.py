from __future__ import annotations

import json
import stat
import sys
import time
from pathlib import Path

import pytest

from lodex_core.management import operations, services, settings, worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.environment import command_argv, inputs
from lodex_core.management.project_config import CONFIG, load
from lodex_core.management.secrets import SQLiteSecrets
from lodex_core.management.store import Registry

from .support.management import register
from .support.operations import recipe


def test_prepare_runs_without_services(registry: Registry, repo: Path) -> None:
    (repo / CONFIG).write_text(
        "schema_version=1\n[commands.prepare]\nargv="
        + json.dumps([sys.executable, "-c", "print('prepared without services')"])
        + "\n"
    )
    task = register(registry, repo)
    assert load(repo / CONFIG)["services"] == {}
    result = operations.run(registry, task, "prepare")
    assert result["state"] == "succeeded" and result["exit_code"] == 0
    assert "prepared without services" in operations.logs(result)["tail"]
    assert registry.all("service") == []


def test_foreground_results_failure_and_shared_secret(registry: Registry, repo: Path) -> None:
    recipe(repo)
    main = register(registry, repo)
    a = worktrees.create(registry, "fixture", "HEAD", "a")
    b = worktrees.create(registry, "fixture", "HEAD", "b")
    provider = SQLiteSecrets(registry)
    provider.set("secret:fixture", "fixture-secret-98abc")
    result = operations.run(registry, a, "prepare")
    assert result["state"] == "succeeded" and result["exit_code"] == 0
    assert result["result"]["resources"][0]["id"] == a["id"]
    assert operations.logs(result)["tail"] == "[REDACTED]\n"
    assert "fixture-secret" not in json.dumps(registry.all("operation"))
    assert registry.db.execute("SELECT value FROM secrets").fetchone()[0] == "fixture-secret-98abc"
    failed = operations.run(registry, a, "verify")
    assert failed["state"] == "failed" and failed["exit_code"] == 3
    assert operations.run(registry, a, "cleanup")["state"] == "succeeded"
    config_path = Path(a["path"]) / CONFIG
    config_path.write_text(config_path.read_text().replace("print(123)", "raise SystemExit(9)"))
    assert operations.run(registry, a, "cleanup")["state"] == "failed"
    worktrees.remove(registry, a, yes=True, force=True)
    assert inputs(registry, b)[1]["TOKEN"] == "fixture-secret-98abc"
    assert inputs(registry, main)[1]["DB"] != inputs(registry, b)[1]["DB"]
    assert main["id"] != a["id"]


def test_env_recipe_export_permissions_and_git_checks(registry: Registry, repo: Path) -> None:
    recipe(repo)
    task = register(registry, repo)
    provider = SQLiteSecrets(registry)
    provider.set("secret:fixture", "fixture-secret-98abc")
    with pytest.raises(ManagementError, match="ignore"):
        settings.export(registry, task, ".env", provider)
    (repo / ".gitignore").write_text(".env\n")
    settings.export(registry, task, ".env", provider)
    assert stat.S_IMODE((repo / ".env").stat().st_mode) == 0o600
    assert "fixture-secret-98abc" in (repo / ".env").read_text()
    config_path = repo / CONFIG
    config_path.write_text(config_path.read_text().replace("app_${LODEX_TASKENV_ID}", "changed"))
    assert settings.show(registry, task)["values"]["DB"] == "changed"
    settings.export(registry, task, ".env", provider)
    assert 'DB="changed"' in (repo / ".env").read_text()
    (repo / ".env").write_text("handwritten")
    with pytest.raises(ManagementError, match="handwritten"):
        settings.export(registry, task, ".env", provider)
    with pytest.raises(ManagementError, match="Git-tracked"):
        settings.export(registry, task, "README.md", provider)
    with pytest.raises(ManagementError, match="inside"):
        settings.export(registry, task, "../outside", provider)
    config_path.write_text(config_path.read_text().replace("secret:fixture", "secret:missing"))
    assert settings.show(registry, task)["secret_refs"] == {"TOKEN": "secret:missing"}
    with pytest.raises(ManagementError, match="Secret is not set"):
        inputs(registry, task, provider)
    config_path.write_text(config_path.read_text().replace("secret:missing", "secret:fixture"))
    assert settings.show(registry, task)["secret_refs"] == {"TOKEN": "secret:fixture"}
    with pytest.raises(ManagementError, match="never argv"):
        command_argv({"argv": ["echo", "${TOKEN}"]}, {"TOKEN": "secret"}, ["secret"])


def test_service_secret_injection_and_denial(registry: Registry, repo: Path) -> None:
    (repo / CONFIG).write_text(
        'schema_version=1\n[secrets]\nTOKEN="secret:fixture"\n[services.worker]\n'
        f'argv=[{json.dumps(sys.executable)},"-u","-c",'
        "\"import os,time; print(os.environ['TOKEN'],flush=True); time.sleep(30)\"]\n"
    )
    task = register(registry, repo)
    provider = SQLiteSecrets(registry)
    provider.set("secret:fixture", "fixture-secret-98abc")
    try:
        record = services.start(registry, task, "worker")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            output = services.logs(registry, task["id"], "worker")["tail"]
            if "[REDACTED]" in output:
                break
            time.sleep(0.02)
        assert "[REDACTED]" in output
        assert "fixture-secret" not in json.dumps(record)
    finally:
        services.stop(registry, task["id"], "worker")

    class Denied(SQLiteSecrets):
        def get(self, reference: str) -> str:
            raise ManagementError("provider_denied", "access denied")

    with pytest.raises(ManagementError, match="access denied"):
        operations.run(registry, task, "prepare", Denied(registry))


def test_setup_incomplete_repo_has_no_invented_commands(registry: Registry, repo: Path) -> None:
    # This repo only contains an initial README: no executable/tool evidence exists.
    (repo / CONFIG).write_text("schema_version=1\n")
    task = register(registry, repo)
    draft = load(repo / CONFIG)
    assert draft["commands"] == {} and draft["services"] == {} and draft["tools"] == []
    with pytest.raises(ManagementError, match="No prepare command"):
        operations.run(registry, task, "prepare")
    assert not registry.all("operation")


def test_malformed_result_and_escaped_secret_redaction(registry: Registry, repo: Path) -> None:
    result = repo / "result.json"
    secret = 'escaped"secret\nvalue'
    result.write_text(
        json.dumps(
            {
                "resources": [
                    {
                        "name": "db",
                        "kind": "fixture",
                        "id": secret,
                        "scope": "shared",
                        "state": "unknown",
                    }
                ]
            }
        )
    )
    assert operations.result_data(result, [secret])["resources"][0]["id"] == "[REDACTED]"
    (repo / CONFIG).write_text(
        "schema_version=1\n[commands.prepare]\n"
        f'argv=[{json.dumps(sys.executable)},"-c",'
        "\"import os; open(os.environ['LODEX_RESULT_FILE'],'w').write('broken')\"]\n"
    )
    task = register(registry, repo)
    observed = operations.run(registry, task, "prepare")
    assert observed["exit_code"] == 0 and observed["state"] == "unknown"
