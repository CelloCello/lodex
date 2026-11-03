from __future__ import annotations

import hashlib
import json
import os
import selectors
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lodex_cli.main import app
from lodex_core.management import services, worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.delegation import Client, receive, send
from lodex_core.management.project_config import CONFIG
from lodex_core.management.secrets import SQLiteSecrets
from lodex_core.management.store import Registry


@pytest.fixture
def delegated(repo: Path) -> Iterator[dict[str, Any]]:
    (repo / "job.py").write_text(
        "import os,time\nprint(os.environ['TOKEN'],flush=True)\ntime.sleep(60)\n"
    )
    (repo / CONFIG).write_text(
        'schema_version=1\n[secrets]\nTOKEN="secret:fixture"\n[services.job]\n'
        f"argv={json.dumps([sys.executable, '-u', 'job.py'])}\n"
        'scripts=["job.py"]\n'
        f"ready_argv={json.dumps([sys.executable, '-c', 'pass'])}\n"
        'ready_timeout=5\nstop_timeout=0.2\n[services.other]\nargv=["true"]\n'
        "[commands.prepare]\n"
        f"argv={json.dumps([sys.executable, '-c', 'pass'])}\n"
        "[commands.cleanup]\n"
        f"argv={json.dumps([sys.executable, '-c', 'pass'])}\n"
    )
    worktrees.git(repo, "add", "job.py", str(CONFIG))
    worktrees.git(repo, "commit", "-qm", "fixture services")
    with tempfile.TemporaryDirectory(prefix="ldc-", dir="/private/tmp") as directory:
        store = Registry(Path(directory) / "state")
        processes: list[subprocess.Popen[str]] = []
        infos = []
        tasks = []
        environment = {**os.environ, "LODEX_HOME": str(store.root), "PYTHONDONTWRITEBYTECODE": "1"}

        def delegate(task: dict[str, Any]) -> dict[str, Any]:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "lodex_cli.main",
                    "service",
                    "delegate",
                    "--target",
                    task["id"],
                    "--service",
                    "job",
                    "--json",
                ],
                cwd=repo,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            processes.append(process)
            assert process.stdout is not None
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=8), "Delegation did not report readiness"
            info = json.loads(process.stdout.readline())
            assert info["ok"], info
            result: dict[str, Any] = info["result"]
            return result

        try:
            worktrees.project_add(store, "fixture", repo, None)
            SQLiteSecrets(store).set("secret:fixture", "synthetic-delegation-token")
            for name in ("a", "b"):
                task = worktrees.create(store, "fixture", "HEAD", "cli-delegate-" + name)
                tasks.append(task)
                infos.append(delegate(task))
            yield {
                "store": store,
                "tasks": tasks,
                "infos": infos,
                "processes": processes,
                "env": environment,
                "delegate": delegate,
            }
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()
            for record in store.all("service"):
                observed = services.refresh(record)
                if (
                    observed["state"] in {"running", "starting", "stopping"}
                    or "terminal" in observed
                ):
                    services.stop(store, record["taskenv"], record["name"])
            for receipt in store.all(services.TERMINAL_KIND):
                if not receipt.get("terminal_acknowledged"):
                    services.retry_acks(store, receipt["taskenv"], receipt["name"])
            store.close()


def test_cli_worker_runs_own_service_without_opening_the_registry(
    delegated: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = delegated["tasks"][0]
    info = delegated["infos"][0]
    monkeypatch.chdir(task["path"])
    monkeypatch.setenv("LODEX_SERVICE_DELEGATION", info["credential_file"])
    monkeypatch.setenv("LODEX_HOME", "/unrelated-and-unwritable-registry")
    monkeypatch.setattr(
        Registry, "__init__", lambda *_a, **_k: pytest.fail("Opened global registry")
    )
    runner = CliRunner()
    listed = runner.invoke(app, ["service", "list", "--json"])
    assert listed.exit_code == 0 and json.loads(listed.stdout)["result"] == []
    denied_context = runner.invoke(app, ["context", "--target", task["path"], "--json"])
    assert denied_context.exit_code == 1
    assert json.loads(denied_context.stdout)["error"]["code"] == "delegation_scope"
    started = runner.invoke(app, ["service", "start", "job", "--json"])
    assert started.exit_code == 0, started.output
    assert json.loads(started.stdout)["result"]["state"] == "running"
    listed = runner.invoke(app, ["service", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    assert [r["name"] for r in json.loads(listed.stdout)["result"]] == ["job"]
    logs = runner.invoke(app, ["service", "logs", "job", "--json"])
    assert logs.exit_code == 0, logs.output
    assert "synthetic-delegation-token" not in logs.stdout
    assert "[REDACTED]" in json.loads(logs.stdout)["result"]["tail"]
    for action in ("start", "stop", "inspect", "logs"):
        denied = runner.invoke(
            app, ["service", action, "job", "--target", delegated["tasks"][1]["id"], "--json"]
        )
        assert denied.exit_code == 1
        assert json.loads(denied.stdout)["error"]["code"] == "delegation_scope"
    denied = runner.invoke(app, ["secret", "list", "--json"])
    assert denied.exit_code == 1
    assert json.loads(denied.stdout)["error"]["code"] == "delegation_scope"
    denied_retry = runner.invoke(app, ["service", "retry-acks", "job", "--json"])
    assert denied_retry.exit_code == 1
    assert json.loads(denied_retry.stdout)["error"]["code"] == "delegation_scope"
    stopped = runner.invoke(app, ["service", "stop", "job", "--json"])
    assert stopped.exit_code == 0, stopped.output
    assert json.loads(stopped.stdout)["result"]["state"] == "stopped"


def test_worker_restarts_modified_application_without_registry_or_recipe_change(
    delegated: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    info, peer_info = delegated["infos"]
    client = Client(Path(info["credential_file"]))
    peer_client = Client(Path(peer_info["credential_file"]))
    peer = peer_client.perform("start", "job", None)
    # The handoff and existing credential already describe the environment.
    assert client.credential["taskenv"] == info["taskenv"]
    assert client.credential["path"] == delegated["tasks"][0]["path"]
    assert client.credential["runtime_root"] == info["runtime_root"]
    assert info["services"] == ["job"]
    monkeypatch.setattr(
        Registry, "__init__", lambda *_a, **_k: pytest.fail("Worker opened central registry")
    )
    first = client.perform("start", "job", None)
    assert client.perform("stop", "job", None)["state"] == "stopped"
    root = Path(client.credential["path"])
    (root / "job.py").write_text(
        "import time\nprint('updated-app' * 8,flush=True)\ntime.sleep(60)\n"
    )
    second = client.perform("start", "job", None)
    assert second["delegated"]["launch"] != first["delegated"]["launch"]
    deadline = time.monotonic() + 3
    while "updated-app" not in client.perform("logs", "job", None)["tail"]:
        assert time.monotonic() < deadline, "Replacement application did not report its version"
        time.sleep(0.02)
    assert peer_client.request("inspect", "job")["pid"] == peer["pid"]
    assert client.perform("stop", "job", None)["state"] == "stopped"
    recipe = root / CONFIG
    recipe.write_text(recipe.read_text() + '\n[env]\nAPP_MODE="changed"\n')
    with pytest.raises(ManagementError) as rejected:
        client.perform("start", "job", None)
    assert rejected.value.code == "delegation_config_changed"


def test_manager_cli_retries_retained_acks_without_stopping_replacement(
    delegated: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = delegated["infos"][0]
    old = Client(Path(info["credential_file"])).perform("start", "job", None)
    monkeypatch.setenv("LODEX_HOME", str(delegated["store"].root))
    runner = CliRunner()
    original = services.record_control

    def invoke(action: str) -> dict[str, Any]:
        result = runner.invoke(
            app, ["service", action, "job", "--target", info["taskenv"], "--json"]
        )
        assert result.exit_code == 0, result.stdout
        value: dict[str, Any] = json.loads(result.stdout)["result"]
        return value

    def reject_ack(value: dict[str, Any], action: str) -> dict[str, Any]:
        if action == "ack_terminal":
            raise ManagementError("unknown_service", "Fixture ACK unavailable")
        return original(value, action)

    with monkeypatch.context() as patch:
        patch.setattr(services, "record_control", reject_ack)
        stopped = invoke("stop")
        replacement = invoke("start")
        assert replacement["state"] == "running"
        expected = [old["delegated"]["launch"]]
        assert stopped["pending_acks"] == replacement["pending_acks"] == expected
        assert invoke("inspect")["pending_acks"] == invoke("logs")["pending_acks"] == expected
        attempted = invoke("retry-acks")
        assert attempted["acknowledged"] == [] and attempted["pending_acks"] == expected
    retried = invoke("retry-acks")
    assert retried["acknowledged"] == expected and retried["pending_acks"] == []
    fresh = invoke("inspect")
    assert fresh["state"] == "running" and fresh["pid"] == replacement["pid"]
    assert "pending_acks" not in fresh and "warning" not in fresh
    assert invoke("retry-acks")["acknowledged"] == []
    assert invoke("stop")["state"] == "stopped"


def test_malformed_supervisor_reply_cannot_break_delegation_or_console(delegated: Any) -> None:
    from lodex_console.actions import overview

    a, b = delegated["infos"]
    client_a, client_b = Client(Path(a["credential_file"])), Client(Path(b["credential_file"]))
    record = client_a.perform("start", "job", None)
    peer = client_b.perform("start", "job", None)
    handle = json.loads(Path(record["delegated"]["control_file"]).read_text())
    endpoint = Path(handle["socket"])
    original = endpoint.with_suffix(".saved")
    endpoint.rename(original)
    done = threading.Event()
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(endpoint))
        server.listen(4)
        server.settimeout(0.1)

        def malformed_replies() -> None:
            while not done.is_set():
                try:
                    connection, _ = server.accept()
                except TimeoutError:
                    continue
                with connection:
                    connection.settimeout(1)
                    connection.recv(4096)
                    connection.sendall(b"[" * 1500 + b"]" * 1500)

        worker = threading.Thread(target=malformed_replies)
        worker.start()
        try:
            assert client_a.request("inspect", "job")["state"] == "unknown"
            assert client_a.perform("list", None, None)[0]["state"] == "unknown"
            with pytest.raises(ManagementError) as rejected:
                client_a.request("stop", "job")
            assert rejected.value.code == "unknown_service"
            snapshot = overview(delegated["store"].root)
            states = {task["id"]: task["services"][0]["state"] for task in snapshot["taskenvs"]}
            assert states[a["taskenv"]] == "unknown" and states[b["taskenv"]] == "running"
            assert client_b.request("inspect", "job")["pid"] == peer["pid"]
            assert delegated["processes"][0].poll() is None
        finally:
            done.set()
            worker.join(timeout=2)
            assert not worker.is_alive()
            endpoint.unlink()
            original.rename(endpoint)
    assert client_a.request("stop", "job")["state"] == "stopped"


def test_wire_protocol_cannot_expand_authority_or_cross_taskenv(delegated: Any) -> None:
    a, b = delegated["infos"]
    client_b = Client(Path(b["credential_file"]))
    running_b = client_b.perform("start", "job", b["taskenv"])
    credential = json.loads(Path(a["credential_file"]).read_text())
    cases: list[dict[str, Any]] = [
        {"target": b["taskenv"]},
        {"action": "cleanup"},
        {"action": "retry-acks"},
        {"action": []},
        {"env": {"LODEX_HOME": str(delegated["store"].root)}},
        {"argv": ["true"]},
        {"token": "非 ASCII"},
    ]
    for extra in cases:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(3)
            connection.connect(a["socket"])
            send(
                connection,
                {
                    "version": 1,
                    "token": credential["token"],
                    "action": "stop",
                    "target": a["taskenv"],
                    "service": "job",
                    **extra,
                },
            )
            assert receive(connection)["ok"] is False
        assert client_b.perform("inspect", "job", b["taskenv"])["pid"] == running_b["pid"]
    assert Client(Path(a["credential_file"])).perform("list", None, a["taskenv"]) == []


@pytest.mark.parametrize("method", ["revoke", "terminate"])
def test_cli_revoke_and_controller_exit_leave_manager_in_control(
    delegated: Any, method: str
) -> None:
    a = delegated["infos"][0]
    client = Client(Path(a["credential_file"]))
    running = client.perform("start", "job", a["taskenv"])
    if method == "revoke":
        result = subprocess.run(
            [sys.executable, "-m", "lodex_cli.main", "service", "revoke", a["id"], "--json"],
            env=delegated["env"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, result.stdout
    else:
        delegated["processes"][0].terminate()
    delegated["processes"][0].wait(timeout=5)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lodex_cli.main",
            "service",
            "stop",
            "job",
            "--target",
            a["taskenv"],
            "--json",
        ],
        env={**delegated["env"], "LODEX_SERVICE_DELEGATION": a["credential_file"]},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "delegation_unavailable"
    store = delegated["store"]
    assert services.refresh(store.get("service", running["id"]))["state"] == "running"
    assert services.stop(store, a["taskenv"], "job")["state"] == "stopped"


@pytest.mark.skipif(
    os.environ.get("LODEX_TEST_SANDBOX") != "1" or sys.platform != "darwin",
    reason="Opt-in disposable macOS Codex sandbox test",
)
@pytest.mark.parametrize("socket_source", ["helper", "profile"])
def test_actual_worker_sandbox_and_service_children_cannot_cross_taskenv(
    delegated: Any, socket_source: str
) -> None:
    codex = shutil.which("codex")
    if codex is None:
        pytest.skip("Codex sandbox helper is not installed")
    a, b = delegated["infos"]
    task_a, task_b = delegated["tasks"]
    store = delegated["store"]
    profiles = [
        Path.home() / ".codex" / (name + ".config.toml")
        for name in ("lodex-manager", "lodex-worker")
    ]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in profiles if p.is_file()}
    peer = Path(task_b["path"]) / "peer-marker"
    peer.write_text("untouched")
    central = store.root / "central-marker"
    central.write_text("untouched")
    client_b = Client(Path(b["credential_file"]))
    running_b = client_b.perform("start", "job", b["taskenv"])
    control_b = json.loads(Path(running_b["delegated"]["control_file"]).read_text())
    attack = {
        "peer": str(peer),
        "central": str(central),
        "credential": b["credential_file"],
        "socket": b["socket"],
        "service_socket": control_b["socket"],
        "peer_pid": running_b["pid"],
    }
    (Path(task_a["path"]) / "attack.json").write_text(json.dumps(attack))
    # Worker edits application code after delegation; the manager never executes it.
    probe = """import errno,json,os,signal,socket,time
from pathlib import Path
attack=json.loads(Path('attack.json').read_text())
proof={}
for key in ('peer','central'):
 try: Path(attack[key]).write_text('cross-task write'); proof[key]=False
 except PermissionError: proof[key]=True
try: Path(attack['credential']).read_text(); proof['credential']=False
except PermissionError: proof['credential']=True
for key in ('socket','service_socket'):
 with socket.socket(socket.AF_UNIX) as client:
  try: client.connect(attack[key]); proof[key]=False
  except OSError as error: proof[key]=error.errno in (errno.EACCES,errno.EPERM)
for key,send in (('process_signal',os.kill),('group_signal',os.killpg)):
 try: send(attack['peer_pid'],signal.SIGTERM); proof[key]=False
 except PermissionError: proof[key]=True
Path('service-sandbox-proof.json').write_text(json.dumps(proof))
print('sandbox-probe-ready',flush=True)
time.sleep(60)
"""
    (Path(task_a["path"]) / "job.py").write_text(probe)
    filesystem = {
        str(store.root): "deny",
        task_a["path"]: "write",
        a["runtime_root"]: "write",
        a["socket"]: "read",
    }
    rules = (
        "{"
        + ",".join(json.dumps(key) + "=" + json.dumps(value) for key, value in filesystem.items())
        + "}"
    )
    overrides = [
        'permissions.lodex-fixture.extends=":workspace"',
        "permissions.lodex-fixture.filesystem=" + rules,
        "permissions.lodex-fixture.network.enabled=false",
    ]
    if socket_source == "profile":
        overrides.extend(
            ["features.network_proxy=true", "permissions.lodex-fixture.network.enabled=true"]
        )
        overrides.append(
            "permissions.lodex-fixture.network.unix_sockets={"
            + ",".join(json.dumps(path) + '="allow"' for path in (a["socket"], a["runtime_root"]))
            + "}"
        )
    command = [codex, "sandbox", "--permission-profile", "lodex-fixture", "--cd", task_a["path"]]
    for override in overrides:
        command.extend(["-c", override])
    if socket_source == "helper":
        command.extend(
            ["--allow-unix-socket", a["socket"], "--allow-unix-socket", a["runtime_root"]]
        )
    script = """import json,os,subprocess,sys,time
from pathlib import Path
target,other=sys.argv[1:]
def run(action,selected=target):
 result=subprocess.run([sys.executable,'-m','lodex_cli.main','service',action,'job','--target',selected,'--json'],capture_output=True,text=True,timeout=15)
 data=json.loads(result.stdout)
 return result.returncode,data
code,data=run('start'); assert code==0,data
path=Path('service-sandbox-proof.json')
deadline=time.monotonic()+3
while not path.exists():
 assert time.monotonic()<deadline
 time.sleep(.02)
proof=json.loads(path.read_text()); assert all(proof.values()),proof
code,data=run('stop',other); assert code==1 and data['error']['code']=='delegation_scope',data
unscoped=dict(os.environ); unscoped.pop('LODEX_SERVICE_DELEGATION')
denied=subprocess.run([sys.executable,'-m','lodex_cli.main','service','stop','job','--target',other,'--json'],env=unscoped,capture_output=True,text=True,timeout=5)
assert denied.returncode!=0,'Removing delegation mode bypassed the sandbox'
code,data=run('stop'); assert code==0 and data['result']['state']=='stopped',data
print(json.dumps({'worker_service_lifecycle':True,'child_sandbox':proof,'cross_target_denied':True}))
"""
    command.extend(["--", sys.executable, "-B", "-c", script, a["taskenv"], b["taskenv"]])
    result = subprocess.run(
        command,
        env={**delegated["env"], "LODEX_SERVICE_DELEGATION": a["credential_file"]},
        capture_output=True,
        text=True,
        timeout=45,
    )
    if result.returncode and "sandbox_apply" in result.stderr:
        pytest.skip("Host cannot enforce a nested Codex sandbox")
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"cross_target_denied": true' in result.stdout
    assert peer.read_text() == central.read_text() == "untouched"
    assert client_b.perform("inspect", "job", b["taskenv"])["pid"] == running_b["pid"]
    assert before == {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in profiles if p.is_file()
    }
