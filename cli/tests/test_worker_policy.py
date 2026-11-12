from __future__ import annotations

import json
import os
import selectors
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lodex_cli import worker_policy
from lodex_cli.main import app
from lodex_core.management import operations, worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.delegation import Client, revoke
from lodex_core.management.project_config import CONFIG

from .test_service_delegation import delegated as delegated


@pytest.mark.skipif(
    os.environ.get("LODEX_TEST_SANDBOX") != "1" or sys.platform != "darwin",
    reason="Opt-in real macOS sandbox boundary test",
)
def test_running_worker_cannot_modify_peer_created_after_launch(
    delegated: Any,
    draft: Any,
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for realpath regression")
    policy = draft["policy"]
    store = delegated["store"]
    task = delegated["tasks"][0]
    # The child stays inside one OS sandbox while the manager creates C.
    program = r"""
const fs=require('fs'), readline=require('readline');
const root=process.cwd();
fs.realpathSync(root); fs.realpathSync(process.env.TMPDIR);
fs.writeFileSync('own-before','ok');
console.log('ready');
readline.createInterface({input:process.stdin}).on('line', line => {
  const {peer,central,peerRuntime}=JSON.parse(line);
  if(fs.readFileSync(peer+'/marker','utf8')!=='untouched') throw Error('peer read');
  const paths=[peer+'/marker',peer+'/new-file',peerRuntime+'/new-file',central+'/management.db'];
  for(const p of paths) {
    try { fs.writeFileSync(p,'changed'); throw Error('write escaped: '+p); }
    catch(e) { if(!['EACCES','EPERM'].includes(e.code)) throw e; }
  }
  try {fs.readFileSync(central+'/management.db'); throw Error('central read');}
  catch(e) {if(!['EACCES','EPERM'].includes(e.code)) throw e;}
  fs.writeFileSync('own-after','ok'); console.log('isolated'); process.exit(0);
});
"""
    child = subprocess.Popen(
        [*policy["sandbox_argv"], "--", node, "-e", program],
        env={**os.environ, **policy["launch_env"], **policy["routes"]},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=10), "Sandbox did not become ready"
        first = child.stdout.readline()
        if first != "ready\n":
            _, error = child.communicate(timeout=5)
            pytest.fail(first + error)
        later = worktrees.create(store, task["project"], "HEAD", "late-peer")
        (Path(later["path"]) / "marker").write_text("untouched")
        from lodex_core.management.workspace import runtime_base

        peer_runtime = runtime_base(store, later)
        peer_runtime.mkdir(parents=True)
        output, error = child.communicate(
            json.dumps(
                {
                    "peer": later["path"],
                    "central": str(store.root),
                    "peerRuntime": str(peer_runtime),
                }
            )
            + "\n",
            timeout=15,
        )
        assert child.returncode == 0, output + error
        assert "isolated" in output
        assert (Path(later["path"]) / "marker").read_text() == "untouched"
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                stream.close()


@pytest.fixture
def draft(delegated: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    if shutil.which("codex") is None:
        # Policy/guard fixtures replace agent_argv before execution. Real Codex
        # integration tests require the installed CLI separately.
        tools = tmp_path / "tools"
        tools.mkdir()
        codex = tools / "codex"
        codex.write_text("#!/bin/sh\necho 'Unexpected policy-only Codex placeholder' >&2\nexit 1\n")
        codex.chmod(0o700)
        monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ.get("PATH", ""))
    home = tmp_path / "codex"
    home.mkdir()
    (home / "fixture.config.toml").write_text('approval_policy="never"\n')
    (home / "config.toml").write_text(
        '[mcp_servers.fixture]\ncommand="false"\n'
        '[plugins."fixture@local"]\nenabled=true\n'
        "[apps.fixture]\nenabled=true\n"
        '[shell_environment_policy.set]\nTOKEN="unrelated-config-value"\nUNRELATED_SECRET="unrelated-synthetic-value"\n'
    )
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("LODEX_HOME", str(delegated["store"].root))
    task = delegated["tasks"][0]
    prepared = operations.run(delegated["store"], task, "prepare")
    arguments = {
        "prepare_operation": prepared["id"],
        "profile": "fixture",
        "cache": tmp_path / "shared-uv",
        "delegation": delegated["infos"][0]["id"],
        "control_sockets": [tmp_path / "herdr.sock"],
    }
    policy = worker_policy.render(delegated["store"], task, **arguments)
    return {"policy": policy, "arguments": arguments, "codex_home": home}


def test_draft_is_task_bound_secret_free_and_does_not_install_profiles(
    delegated: Any, draft: Any
) -> None:
    policy = draft["policy"]
    root = delegated["store"].root
    assert policy["filesystem"][str(root)] == "deny"
    assert policy["filesystem"][delegated["tasks"][1]["path"]] == "read"
    assert policy["filesystem"][delegated["tasks"][0]["path"]] == "write"
    assert policy["routes"]["LODEX_SERVICE_DELEGATION"] == delegated["infos"][0]["credential_file"]
    assert "synthetic-delegation-token" not in json.dumps(policy)
    assert policy["applied"] is False
    assert sorted(p.name for p in draft["codex_home"].iterdir()) == [
        "config.toml",
        "fixture.config.toml",
    ]
    for section, identity in (
        ("mcp_servers", "fixture"),
        ("plugins", "fixture@local"),
        ("apps", "fixture"),
    ):
        override = next(arg for arg in policy["agent_argv"] if arg.startswith(section + "="))
        assert tomllib.loads(override)[section][identity]["enabled"] is False
    mcp = tomllib.loads(next(arg for arg in policy["agent_argv"] if arg.startswith("mcp_servers=")))
    assert mcp["mcp_servers"]["codex_worktrees"]["enabled"] is False
    assert mcp["mcp_servers"]["codex_tui"]["enabled"] is False
    assert "features.multi_agent_v2=false" in policy["agent_argv"]
    assert "features.multi_agent_v2_dynamic_tools=false" in policy["agent_argv"]
    assert (
        worker_policy.read(delegated["store"], delegated["tasks"][0], Path(policy["policy_file"]))[
            "id"
        ]
        == policy["id"]
    )
    with pytest.raises(ManagementError):
        worker_policy.read(delegated["store"], delegated["tasks"][1], Path(policy["policy_file"]))
    untrusted = Path(delegated["tasks"][0]["path"]) / "policy.json"
    untrusted.write_text(json.dumps(policy))
    with pytest.raises(ManagementError):
        worker_policy.read(delegated["store"], delegated["tasks"][0], untrusted)


def test_old_overlapping_registration_cannot_issue_or_reuse_policy(
    delegated: Any, draft: Any
) -> None:
    store, task = delegated["store"], delegated["tasks"][0]
    policy = draft["policy"]
    saved = Path(policy["policy_file"]).read_bytes()
    task["workspace_root"] = task["path"]
    store.put("taskenv", task)
    with pytest.raises(ManagementError) as issuing:
        worker_policy.render(store, task, **draft["arguments"])
    assert issuing.value.code == "workspace_overlap"
    with pytest.raises(ManagementError) as reading:
        worker_policy.read(store, task, Path(policy["policy_file"]))
    assert reading.value.code == "workspace_overlap"
    assert Path(policy["policy_file"]).read_bytes() == saved


def test_nested_registration_remains_manageable_but_cannot_issue_isolated_worker_policy(
    delegated: Any, draft: Any
) -> None:
    store, task = delegated["store"], delegated["tasks"][0]
    nested = Path(task["path"]) / "nested"
    worktrees.git(Path(task["common"]), "worktree", "add", "--detach", str(nested), "HEAD")
    inner = worktrees.attach(store, task["project"], nested)
    assert worktrees.resolve(store, str(nested))["id"] == inner["id"]
    for candidate in (task, inner):
        with pytest.raises(ManagementError) as error:
            worker_policy.render(store, candidate, **draft["arguments"])
        assert error.value.code == "workspace_overlap"


def test_restricted_cleanup_rechecks_overlap_under_its_task_lock(
    delegated: Any, draft: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, task = delegated["store"], delegated["tasks"][0]
    nested = Path(task["path"]) / "nested"
    worktrees.git(Path(task["common"]), "worktree", "add", "--detach", str(nested), "HEAD")
    read = worker_policy.read_snapshot

    def read_before_registration(*args: Any) -> dict[str, Any]:
        policy = read(*args)
        worktrees.attach(store, task["project"], nested)
        return policy

    monkeypatch.setattr(worker_policy, "read_snapshot", read_before_registration)
    result = CliRunner().invoke(
        app,
        [
            "cleanup",
            "--target",
            task["id"],
            "--worker-policy",
            draft["policy"]["policy_file"],
            "--json",
        ],
    )
    assert (
        result.exit_code != 0 and json.loads(result.stdout)["error"]["code"] == "workspace_overlap"
    )
    assert not any(op["command"] == "cleanup" for op in store.all("operation"))


def test_policy_ignores_legacy_inode_but_rebind_invalidates_policy_and_prepare(
    delegated: Any, draft: Any
) -> None:
    store, task = delegated["store"], delegated["tasks"][0]
    task.update(inode=[1, 2], git_inode=[3, 4], common_inode=[5, 6])
    store.put("taskenv", task)
    policy_path = Path(draft["policy"]["policy_file"])
    assert worker_policy.read(store, task, policy_path)["id"] == draft["policy"]["id"]
    revoke(store, delegated["infos"][0]["id"])
    worktrees.attach(store, task["project"], Path(task["path"]), rebind=True, yes=True)
    with pytest.raises(ManagementError) as stale:
        worker_policy.read(store, task, policy_path)
    assert stale.value.code == "identity_changed"
    operations.run(store, task, "prepare")
    with pytest.raises(ManagementError) as unprepared:
        worker_policy.render(store, task, **draft["arguments"])
    assert unprepared.value.code == "worker_unprepared"


def test_recipe_or_legacy_settings_require_explicit_review(delegated: Any, draft: Any) -> None:
    task = delegated["tasks"][0]
    recipe = Path(task["path"]) / CONFIG
    before = recipe.read_text()
    recipe.write_text(before + '\n[env]\nMODE="changed"\n')
    with pytest.raises(ManagementError) as changed:
        worker_policy.render(delegated["store"], task, **draft["arguments"])
    assert changed.value.code == "worker_unprepared"
    recipe.write_text(before)
    (draft["codex_home"] / "config.toml").write_text('sandbox_mode="workspace-write"\n')
    with pytest.raises(ManagementError, match="Legacy sandbox"):
        worker_policy.render(delegated["store"], task, **draft["arguments"])


def test_explicit_checkout_trust_and_private_paths_remain_invocation_only(
    delegated: Any, draft: Any
) -> None:
    settings = draft["codex_home"] / "config.toml"
    before = settings.read_bytes()
    task = delegated["tasks"][0]
    assert draft["policy"]["trust_checkout"] is False
    policy = worker_policy.render(
        delegated["store"],
        task,
        **draft["arguments"],
        denied_paths=[draft["codex_home"]],
        trust_checkout=True,
    )
    assert settings.read_bytes() == before
    assert policy["filesystem"][str(draft["codex_home"])] == "deny"
    override = next(arg for arg in policy["agent_argv"] if arg.startswith("projects="))
    assert tomllib.loads(override)["projects"] == {task["path"]: {"trust_level": "trusted"}}


def test_worker_config_cli_drafts_without_holding_controller_task_lock(
    delegated: Any, draft: Any
) -> None:
    arguments = draft["arguments"]
    result = CliRunner().invoke(
        app,
        [
            "worktree",
            "worker-config",
            "--target",
            delegated["tasks"][0]["id"],
            "--prepare-operation",
            arguments["prepare_operation"],
            "--profile",
            "fixture",
            "--uv-cache",
            str(arguments["cache"]),
            "--delegation",
            arguments["delegation"],
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["result"]["applied"] is False


def test_cleanup_cannot_resolve_new_secret_references_from_modified_recipe(
    delegated: Any, draft: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lodex_core.management.secrets import SQLiteSecrets

    task = delegated["tasks"][0]
    recipe = Path(task["path"]) / CONFIG
    recipe.write_text(recipe.read_text().replace("secret:fixture", "secret:other-project"))
    monkeypatch.setattr(SQLiteSecrets, "get", lambda *_: pytest.fail("Read an unapproved secret"))
    result = CliRunner().invoke(
        app,
        [
            "cleanup",
            "--target",
            task["id"],
            "--worker-policy",
            draft["policy"]["policy_file"],
            "--json",
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "execution_scope"
    assert not [op for op in delegated["store"].all("operation") if op["command"] == "cleanup"]


def test_new_grant_generates_new_routes_without_old_runtime_or_peer_changes(
    delegated: Any, draft: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store, task = delegated["store"], delegated["tasks"][0]
    old, peer = delegated["infos"]
    old_client = Client(Path(old["credential_file"]))
    old_service = old_client.perform("start", "job", None)
    peer_client = Client(Path(peer["credential_file"]))
    peer_service = peer_client.perform("start", "job", None)
    delegated["processes"][0].terminate()
    delegated["processes"][0].wait(timeout=5)
    replacement = delegated["delegate"](task)
    monkeypatch.setenv("LODEX_WORKSPACE_ROOT", str(tmp_path / "future-workspaces"))
    arguments = {**draft["arguments"], "delegation": replacement["id"]}
    fresh = worker_policy.render(store, task, **arguments)
    assert fresh["taskenv"] == draft["policy"]["taskenv"]
    assert Path(fresh["runtime_root"]).is_relative_to(Path(task["workspace_root"]))
    assert fresh["permission_profile"] != draft["policy"]["permission_profile"]
    assert fresh["routes"]["LODEX_SERVICE_DELEGATION"] == replacement["credential_file"]
    assert old["runtime_root"] not in fresh["filesystem"]
    assert old["socket"] not in fresh["sockets"]
    with pytest.raises(ManagementError) as denied:
        old_client.request("list")
    assert denied.value.code == "delegation_unavailable"
    client = Client(Path(replacement["credential_file"]))
    assert client.request("inspect", "job")["pid"] == old_service["pid"]
    assert client.perform("stop", "job", None)["state"] == "stopped"
    restarted = client.perform("start", "job", None)
    assert restarted["delegated"]["root"] == replacement["runtime_root"]
    assert peer_client.request("inspect", "job")["pid"] == peer_service["pid"]
    assert client.perform("stop", "job", None)["state"] == "stopped"


@pytest.mark.skipif(
    os.environ.get("LODEX_TEST_SANDBOX") != "1"
    or sys.platform != "darwin"
    or shutil.which("codex") is None,
    reason="Opt-in disposable Codex sandbox test",
)
def test_rendered_policy_routes_own_services_without_helper_socket_flags(
    delegated: Any, draft: Any
) -> None:
    policy = draft["policy"]
    program = """import os
from pathlib import Path
from lodex_core.management.delegation import Client
client=Client(Path(os.environ['LODEX_SERVICE_DELEGATION']))
assert Path.cwd()==Path(client.credential['path'])
Path(os.environ['TMPDIR']).joinpath('own-temp').write_text('allowed')
assert client.perform('start','job',None)['state']=='running'
assert client.perform('stop','job',None)['state']=='stopped'
print('own-service-and-temp-allowed')
"""
    environment = {**os.environ, **policy["launch_env"]}
    environment.pop("LODEX_SERVICE_DELEGATION", None)
    result = subprocess.run(
        [*policy["sandbox_argv"], "--", sys.executable, "-c", program],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "own-service-and-temp-allowed" in result.stdout


@pytest.mark.skipif(
    os.environ.get("LODEX_TEST_SANDBOX") != "1"
    or sys.platform != "darwin"
    or shutil.which("codex") is None,
    reason="Opt-in disposable Codex sandbox test",
)
def test_restricted_cleanup_collects_results_without_central_access_or_peer_writes(
    delegated: Any, draft: Any
) -> None:
    task, peer = delegated["tasks"]
    root = Path(task["path"])
    central = delegated["store"].root / "management.db"
    marker = Path(peer["path"]) / "peer-marker"
    marker.write_text("untouched")
    script = f"""import json,os
from pathlib import Path
assert os.environ['TOKEN']=='synthetic-delegation-token'
assert 'UNRELATED_SECRET' not in os.environ
for path in ({str(central)!r},):
 try: Path(path).read_bytes()
 except PermissionError: pass
 else: raise SystemExit('central read allowed')
assert Path({str(marker)!r}).read_text() == 'untouched'
try: Path({str(marker)!r}).write_text('changed')
except PermissionError: pass
else: raise SystemExit('cross-task write allowed')
Path('cleanup-complete').write_text('own taskenv')
Path(os.environ['LODEX_RESULT_FILE']).write_text(json.dumps({{'resources':[],'urls':[]}}))
"""
    (root / "cleanup.py").write_text(script)
    recipe = root / CONFIG
    # The task agent may edit cleanup after dispatch. A still executes it only
    # through the task's previously reviewed OS restrictions.
    recipe.write_text(
        recipe.read_text().replace(
            "[commands.cleanup]\nargv=" + json.dumps([sys.executable, "-c", "pass"]),
            "[commands.cleanup]\nargv=" + json.dumps([sys.executable, "cleanup.py"]),
        )
    )
    result = CliRunner().invoke(
        app,
        [
            "cleanup",
            "--target",
            task["id"],
            "--worker-policy",
            draft["policy"]["policy_file"],
            "--json",
        ],
    )
    record = json.loads(result.stdout)["result"]
    assert result.exit_code == 0, result.stdout + operations.logs(record)["tail"]
    assert record["result"] == {"resources": [], "urls": []}
    assert (root / "cleanup-complete").read_text() == "own taskenv"
    assert marker.read_text() == "untouched"
    (root / "cleanup.py").write_text("raise SystemExit(9)\n")
    failed = CliRunner().invoke(
        app,
        [
            "cleanup",
            "--target",
            task["id"],
            "--worker-policy",
            draft["policy"]["policy_file"],
            "--json",
        ],
    )
    assert failed.exit_code == 1
    assert json.loads(failed.stdout)["result"]["state"] == "failed"
    assert delegated["store"].get("service-delegation", delegated["infos"][0]["id"])["active"]
    assert root.is_dir() and marker.read_text() == "untouched"


@pytest.mark.skipif(
    os.environ.get("LODEX_TEST_SANDBOX") != "1" or sys.platform != "darwin",
    reason="Opt-in real loopback service sandbox test",
)
@pytest.mark.parametrize(
    "readiness,binding",
    [("ready_port", None), ("ready_argv", True), ("ready_argv", False), ("ready_port", False)],
)
def test_grant_runs_real_http_service_in_worker_sandbox(
    delegated: Any,
    draft: Any,
    readiness: str,
    binding: bool | None,
) -> None:
    store, task = delegated["store"], delegated["tasks"][0]
    delegated["processes"][0].terminate()
    delegated["processes"][0].wait(timeout=5)
    root = Path(task["path"])
    (root / "job.py").write_text(
        "import os\nfrom http.server import HTTPServer,SimpleHTTPRequestHandler\n"
        "HTTPServer(('127.0.0.1',int(os.environ['PORT'])),SimpleHTTPRequestHandler).serve_forever()\n"
    )
    recipe = root / CONFIG
    ready = 'ready_port="PORT"'
    if readiness == "ready_argv":
        probe = "import os,urllib.request;assert urllib.request.urlopen('http://127.0.0.1:'+os.environ['PORT']+'/README.md',timeout=1).status==200"
        ready = "ready_argv=" + json.dumps([sys.executable, "-c", probe])
    if binding is not None:
        ready += "\nallow_local_binding=" + str(binding).lower()
    recipe.write_text(
        recipe.read_text().replace(
            "ready_argv=" + json.dumps([sys.executable, "-c", "pass"]),
            ready,
        )
        + "\n[ports]\nPORT=0\n"
    )
    prepared = operations.run(store, task, "prepare")
    grant = delegated["delegate"](task)
    policy = worker_policy.render(
        store,
        task,
        **{
            **draft["arguments"],
            "prepare_operation": prepared["id"],
            "delegation": grant["id"],
            "hosts": ["127.0.0.1"],
        },
    )
    program = """import os,urllib.request
from pathlib import Path
from lodex_core.management.delegation import Client
client=Client(Path(os.environ['LODEX_SERVICE_DELEGATION']))
try:
 client.perform('start','job',None)
 response=urllib.request.urlopen('http://127.0.0.1:PORT/README.md',timeout=5)
 assert response.status==200
 print('http-ready')
finally:
 assert client.perform('stop','job',None)['state']=='stopped'
""".replace("PORT", str(task["ports"]["PORT"]))
    expected = "http-ready"
    if binding is False:
        program = f"""import socket
with socket.socket() as sock:
 try: sock.bind(('127.0.0.1',{task["ports"]["PORT"]}))
 except PermissionError: print('binding-denied')
 else: raise AssertionError('unapproved local binding')
"""
        expected = "binding-denied"
    result = subprocess.run(
        [*policy["sandbox_argv"], "--", sys.executable, "-c", program],
        env={**os.environ, **policy["launch_env"]},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert expected in result.stdout


@pytest.mark.skipif(
    os.environ.get("LODEX_TEST_SANDBOX") != "1"
    or sys.platform != "darwin"
    or shutil.which("codex") is None,
    reason="Opt-in disposable Codex sandbox test",
)
@pytest.mark.parametrize("injection", ["NODE_OPTIONS", "PATH"])
def test_cleanup_loader_environment_is_applied_only_inside_sandbox(
    delegated: Any, draft: Any, injection: str
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed for the loader environment probe")
    task = delegated["tasks"][0]
    root = Path(task["path"])
    marker = delegated["store"].root / "manager-marker"
    marker.write_text("untouched")
    proof = root / "loader-denied"
    # The same loader must fail to write central state when it runs as part of
    # the cleanup. Running it before the sandbox instead would change the marker.
    javascript = (
        'const fs=require("node:fs");\n'
        "try { fs.writeFileSync(" + json.dumps(str(marker)) + ',"escaped"); }\n'
        "catch (e) {\n"
        ' if (!["EACCES","EPERM"].includes(e.code)) throw e;\n'
        " fs.writeFileSync(" + json.dumps(str(proof)) + ',"denied");\n}\n'
    )
    if injection == "NODE_OPTIONS":
        loader = root / "loader.cjs"
        loader.write_text(javascript)
        value = "--preserve-symlinks --require=" + str(loader)
    else:
        directory = root / "bin"
        directory.mkdir()
        loader = directory / "node"
        probe = (
            "from pathlib import Path\n"
            "try: Path(" + repr(str(marker)) + ").write_text('escaped')\n"
            "except PermissionError: Path(" + repr(str(proof)) + ").write_text('denied')\n"
        )
        loader.write_text(
            "#!/bin/sh\n"
            + shlex.join([sys.executable, "-I", "-c", probe])
            + "\nexec "
            + shlex.quote(node)
            + ' "$@"\n'
        )
        loader.chmod(0o700)
        value = str(directory) + os.pathsep + os.environ.get("PATH", "")
    (root / "cleanup.py").write_text(
        "import json,os,subprocess\nfrom pathlib import Path\n"
        "assert os.environ['PROJECT_ONLY']=='repo input'\n"
        "assert os.environ['TOKEN']=='synthetic-delegation-token'\n"
        "subprocess.run(['node','-e',''],check=True)\n"
        "Path(os.environ['LODEX_RESULT_FILE']).write_text(json.dumps({'resources':[],'urls':[]}))\n"
    )
    recipe = root / CONFIG
    recipe.write_text(
        recipe.read_text().replace(
            "[commands.cleanup]\nargv=" + json.dumps([sys.executable, "-c", "pass"]),
            "[commands.cleanup]\nargv=" + json.dumps([sys.executable, "cleanup.py"]),
        )
        + '\n[env]\nPROJECT_ONLY="repo input"\n'
        + injection
        + "="
        + json.dumps(value)
        + "\n"
    )
    result = CliRunner().invoke(
        app,
        [
            "cleanup",
            "--target",
            task["id"],
            "--worker-policy",
            draft["policy"]["policy_file"],
            "--json",
        ],
    )
    record = json.loads(result.stdout)["result"]
    assert marker.read_text() == "untouched"
    assert result.exit_code == 0, result.stdout + operations.logs(record)["tail"]
    assert proof.read_text() == "denied"
    assert record["result"] == {"resources": [], "urls": []}
