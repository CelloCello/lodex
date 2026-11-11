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


def test_restricted_operation_passes_project_inputs_only_through_pipe(
    registry: Registry, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_NETWORK_PROXY_ACTIVE", "1")
    monkeypatch.setenv("HTTPS_PROXY", "http://manager-only.invalid:1234")
    (repo / "cleanup.py").write_text(
        "import os\n"
        "assert os.environ['PROJECT_ONLY']=='repo input'\n"
        "assert os.environ['TOKEN']=='synthetic-cleanup-secret'\n"
        "assert os.environ['TRUSTED_ROUTE']=='reviewed route'\n"
        "assert 'HTTPS_PROXY' not in os.environ\n"
        "assert 'CODEX_NETWORK_PROXY_ACTIVE' not in os.environ\n"
        "print('repo inputs delivered')\n"
    )
    (repo / CONFIG).write_text(
        'schema_version=1\n[env]\nPROJECT_ONLY="repo input"\n'
        '[secrets]\nTOKEN="secret:cleanup"\n[commands.cleanup]\nargv='
        + json.dumps([sys.executable, "cleanup.py"])
        + "\n"
    )
    task = register(registry, repo)
    SQLiteSecrets(registry).set("secret:cleanup", "synthetic-cleanup-secret")
    launcher = (
        "import json,os,sys\n"
        "assert 'PROJECT_ONLY' not in os.environ\n"
        "assert 'TOKEN' not in os.environ\n"
        "assert 'LODEX_RESULT_FILE' not in os.environ\n"
        "assert 'HTTPS_PROXY' not in os.environ\n"
        "assert 'CODEX_NETWORK_PROXY_ACTIVE' not in os.environ\n"
        "assert os.environ['TRUSTED_ROUTE']=='reviewed route'\n"
        "payload=json.load(sys.stdin)\n"
        "os.execvpe(payload['argv'][0],payload['argv'],payload['environment'])\n"
    )
    result = operations.run(
        registry,
        task,
        "cleanup",
        execution=lambda _result: [sys.executable, "-I", "-c", launcher],
        execution_env={"TRUSTED_ROUTE": "reviewed route"},
    )
    assert result["state"] == "succeeded", operations.logs(result)["tail"]
    assert "repo inputs delivered" in operations.logs(result)["tail"]


@pytest.mark.parametrize("active", [False, True])
def test_direct_prepare_retains_only_active_caller_network_route(
    registry: Registry, repo: Path, monkeypatch: pytest.MonkeyPatch, active: bool
) -> None:
    monkeypatch.delenv("CODEX_NETWORK_PROXY_ACTIVE", raising=False)
    if active:
        monkeypatch.setenv("CODEX_NETWORK_PROXY_ACTIVE", "1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:12345")
    monkeypatch.setenv("npm_config_https_proxy", "http://127.0.0.1:12345")
    monkeypatch.setenv("NODE_USE_ENV_PROXY", "1")
    monkeypatch.setenv("UNRELATED_PROJECT_TOKEN", "must-not-inherit")
    script = (
        "import os,json;from pathlib import Path;"
        "Path('seen.json').write_text(json.dumps({k:os.environ.get(k) for k in "
        "['HTTPS_PROXY','npm_config_https_proxy','NODE_USE_ENV_PROXY','ALL_PROXY',"
        "'CODEX_NETWORK_PROXY_ACTIVE','UNRELATED_PROJECT_TOKEN']}))"
    )
    monkeypatch.delenv("ALL_PROXY", raising=False)
    (repo / CONFIG).write_text(
        'schema_version=1\n[env]\nHTTPS_PROXY="http://project.invalid:80"\n'
        'ALL_PROXY="http://stale-project.invalid:80"\n[commands.prepare]\nargv='
        + json.dumps([sys.executable, "-c", script]) + "\n"
    )
    task = register(registry, repo)
    result = operations.run(registry, task, "prepare")
    assert result["state"] == "succeeded", operations.logs(result)["tail"]
    seen = json.loads((repo / "seen.json").read_text())
    assert seen["UNRELATED_PROJECT_TOKEN"] is None
    assert seen["HTTPS_PROXY"] == (
        "http://127.0.0.1:12345" if active else "http://project.invalid:80"
    )
    assert seen["npm_config_https_proxy"] == ("http://127.0.0.1:12345" if active else None)
    assert seen["NODE_USE_ENV_PROXY"] == ("1" if active else None)
    assert seen["CODEX_NETWORK_PROXY_ACTIVE"] == ("1" if active else None)
    assert seen["ALL_PROXY"] == (None if active else "http://stale-project.invalid:80")
    assert "127.0.0.1:12345" not in json.dumps(result)


def test_prepare_delivers_project_env_and_secret_free_handoff_for_two_taskenvs(
    registry: Registry, repo: Path
) -> None:
    (repo / ".gitignore").write_text(".env\n")
    script = (
        "import os;from pathlib import Path; "
        "assert os.environ['TOKEN'] in Path('.env').read_text(); "
        "Path('prepared').write_text(os.environ['LODEX_TASKENV_ID'])"
    )
    (repo / CONFIG).write_text(
        'schema_version=1\n[taskenv]\nenv_file=".env"\n'
        '[env]\nDB="app_${LODEX_TASKENV_ID}"\n'
        '[secrets]\nTOKEN="secret:shared"\n[commands.prepare]\nargv='
        + json.dumps([sys.executable, "-c", script])
        + "\n"
    )
    worktrees.git(repo, "add", ".gitignore", str(CONFIG))
    worktrees.git(repo, "commit", "-qm", "taskenv configuration")
    worktrees.project_add(registry, "fixture", repo, None)
    provider = SQLiteSecrets(registry)
    provider.set("secret:shared", "synthetic-shared-value")
    (repo / ".env").write_text("source handwritten settings")
    a = worktrees.create(registry, "fixture", "HEAD", "a")
    b = worktrees.create(registry, "fixture", "HEAD", "b")
    for task in (a, b):
        root = Path(task["path"])
        assert not (root / ".env").exists()
        result = operations.run(registry, task, "prepare")
        assert result["state"] == "succeeded"
        handoff = result["handoff"]
        assert handoff["taskenv"] == task["id"]
        assert handoff["path"] == str(root)
        assert handoff["env_file"] == str(root / ".env")
        assert handoff["base_commit"] == worktrees.git(repo, "rev-parse", "HEAD")
        assert handoff["secret_refs"] == {"TOKEN": "secret:shared"}
        assert "synthetic-shared-value" not in json.dumps(result)
        assert stat.S_IMODE((root / ".env").stat().st_mode) == 0o600
        assert f'DB="app_{task["id"]}"' in (root / ".env").read_text()
        assert (root / "prepared").read_text() == task["id"]
    snapshot = (Path(b["path"]) / ".env").read_text()
    provider.set("secret:shared", "synthetic-refreshed-value")
    operations.run(registry, a, "prepare")
    assert "synthetic-refreshed-value" in (Path(a["path"]) / ".env").read_text()
    assert (Path(b["path"]) / ".env").read_text() == snapshot
    assert (repo / ".env").read_text() == "source handwritten settings"


def test_prepare_failure_and_export_protection_keep_same_taskenv(
    registry: Registry, repo: Path
) -> None:
    (repo / CONFIG).write_text(
        'schema_version=1\n[taskenv]\nenv_file=".env"\n'
        "[commands.prepare]\nargv="
        + json.dumps([sys.executable, "-c", "raise SystemExit(9)"])
        + "\n"
    )
    task = register(registry, repo)
    for _ in range(2):
        failed = operations.run(registry, task, "prepare")
        assert failed["state"] == "failed" and "handoff" not in failed
    assert len(registry.all("taskenv")) == 1
    assert registry.all("taskenv")[0]["id"] == task["id"]
    (repo / ".env").write_text("handwritten")
    with pytest.raises(ManagementError) as rejected:
        operations.run(registry, task, "prepare")
    assert rejected.value.code == "unmanaged_env"
    assert (repo / ".env").read_text() == "handwritten"
    assert len(registry.all("operation")) == 2


@pytest.mark.parametrize("output", ["", ".", "../outside", "/absolute", ".git/config", 3])
def test_project_env_delivery_requires_relative_regular_file(repo: Path, output: object) -> None:
    (repo / CONFIG).write_text("schema_version=1\n[taskenv]\nenv_file=" + json.dumps(output))
    with pytest.raises(ManagementError) as rejected:
        load(repo / CONFIG)
    assert rejected.value.code == "invalid_config"


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


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_result_collection_rejects_worker_replaced_files(tmp_path: Path, kind: str) -> None:
    import os

    central = tmp_path / "central.json"
    central.write_text('{"urls":["https://private.invalid/"]}')
    result = tmp_path / "result.json"
    if kind == "symlink":
        result.symlink_to(central)
    elif kind == "hardlink":
        os.link(central, result)
    else:
        os.mkfifo(result)
    with pytest.raises(ManagementError) as rejected:
        operations.result_data(result, [])
    assert rejected.value.code == "invalid_result"
