from __future__ import annotations

import json
import os
import signal
import socket
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from lodex_core.management import services, worktrees
from lodex_core.management.common import ManagementError
from lodex_core.management.delegation import VERSION, Controller, revoke
from lodex_core.management.project_config import CONFIG, load
from lodex_core.management.secrets import SQLiteSecrets
from lodex_core.management.store import Registry


@pytest.fixture
def grants(repo: Path) -> Iterator[tuple[Registry, Controller, Controller]]:
    worker = "import os,time;print(os.environ['TOKEN']);time.sleep(60)"
    (repo / CONFIG).write_text(
        'schema_version=1\n[env]\nTASK="${LODEX_TASKENV_ID}"\n'
        '[secrets]\nTOKEN="secret:self"\n[services.job]\n'
        f"argv={json.dumps([sys.executable, '-u', '-c', worker])}\n"
        f"ready_argv={json.dumps([sys.executable, '-c', 'pass'])}\n"
        'ready_timeout=3\nstop_timeout=0.1\n[services.other]\nargv=["true"]\n'
    )
    # Keep Unix socket paths short on both Linux and macOS.
    with tempfile.TemporaryDirectory(prefix="ldg-", dir=Path("/tmp").resolve()) as directory:
        registry = Registry(Path(directory) / "state")
        controllers: list[Controller] = []
        try:
            worktrees.project_add(registry, "fixture", repo, None)
            SQLiteSecrets(registry).set("secret:self", "fixture-self-token")
            for branch in ("delegate-a", "delegate-b"):
                task = worktrees.create(registry, "fixture", "HEAD", branch)
                controllers.append(Controller(registry, task, ["job"]))
            yield registry, controllers[0], controllers[1]
        finally:
            for record in registry.all("service"):
                observed = services.refresh(record)
                if (
                    observed["state"] in {"starting", "running", "stopping"}
                    or "terminal" in observed
                ):
                    services.stop(registry, record["taskenv"], record["name"])
            for receipt in registry.all(services.TERMINAL_KIND):
                if not receipt.get("terminal_acknowledged"):
                    services.retry_acks(registry, receipt["taskenv"], receipt["name"])
            for controller in controllers:
                controller.close()
            registry.close()


def request(controller: Controller, operation: str, **extra: Any) -> dict[str, Any]:
    return {
        "version": VERSION,
        "token": controller.token,
        "action": operation,
        "target": controller.task["id"],
        **({"service": "job"} if operation != "list" else {}),
        **extra,
    }


def start(controller: Controller) -> dict[str, Any]:
    prepared = controller.dispatch(request(controller, "start"))
    observed = services.launch(prepared["record"], prepared["payload"])
    assert observed["state"] == "running"
    return controller.dispatch(request(controller, "inspect"))


@pytest.mark.parametrize("action", ["start", "stop", "list", "inspect", "logs"])
@pytest.mark.parametrize("selector", ["id", "path"])
def test_scope_denies_other_taskenv_without_affecting_it(
    grants: Any,
    action: str,
    selector: str,
) -> None:
    registry, a, b = grants
    running = start(b)
    target = b.task["id"] if selector == "id" else b.task["path"]
    before = registry.get("service", running["id"])
    with pytest.raises(ManagementError, match="outside this delegation"):
        a.dispatch(request(a, action, target=target))
    after = b.dispatch(request(b, "inspect"))
    assert after["state"] == "running" and after["pid"] == running["pid"]
    assert registry.get("service", running["id"])["directory"] == before["directory"]


@pytest.mark.parametrize(
    "extra",
    [
        {"service": "other"},
        {"service": "../other"},
        {"env": {}},
        {"argv": ["true"]},
        {"action": "cleanup"},
        {"action": []},
        {"token": "wrong"},
        {"token": "非 ASCII"},
        {"version": True},
    ],
)
def test_scope_rejects_unapproved_services_actions_and_payloads(grants: Any, extra: Any) -> None:
    registry, a, _ = grants
    before = registry.all("service")
    with pytest.raises(ManagementError):
        a.dispatch(request(a, "start", **extra))
    assert registry.all("service") == before


def test_controller_reserves_but_does_not_execute_repo_code(
    grants: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, a, _ = grants
    monkeypatch.setattr(services, "launch", lambda *_: pytest.fail("Manager executed repo code"))
    result = a.dispatch(request(a, "start"))
    assert result["payload"]["env"]["TOKEN"] == "fixture-self-token"
    assert not Path(result["record"]["directory"]).exists()
    assert registry.get("service", result["record"]["id"])["state"] == "starting"


def test_changed_recipe_cannot_expand_secret_authority(
    grants: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, a, _ = grants
    path = Path(a.task["path"]) / CONFIG
    path.write_text(path.read_text().replace("secret:self", "secret:other-task"))
    monkeypatch.setattr(SQLiteSecrets, "get", lambda *_: pytest.fail("Read an unapproved secret"))
    with pytest.raises(ManagementError, match="Recipe changed"):
        a.dispatch(request(a, "start"))


def test_revocation_preserves_services_for_manager_takeover(grants: Any) -> None:
    registry, a, b = grants
    running = start(a)
    revoke(registry, a.identity)
    with pytest.raises(ManagementError, match="inactive"):
        a.dispatch(request(a, "stop"))
    assert services.refresh(registry.get("service", running["id"]))["state"] == "running"
    assert b.dispatch(request(b, "list")) == {"services": []}
    assert services.stop(registry, a.task["id"], "job")["state"] == "stopped"


def test_recipe_race_cannot_change_the_authorized_launch_inputs(
    grants: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lodex_core.management import delegation

    _, a, _ = grants
    path = Path(a.task["path"]) / CONFIG
    original = load

    def swap_after_check(location: Path) -> dict[str, Any]:
        approved = original(location)
        path.write_text(path.read_text().replace("secret:self", "secret:other-task"))
        return approved

    monkeypatch.setattr(delegation, "load", swap_after_check)
    prepared = a.dispatch(request(a, "start"))
    assert prepared["payload"]["env"]["TOKEN"] == "fixture-self-token"


def test_worker_control_file_cannot_redirect_manager_to_another_taskenv(grants: Any) -> None:
    registry, a, b = grants
    record_a, record_b = start(a), start(b)
    control_b = json.loads(Path(record_b["delegated"]["control_file"]).read_text())
    (Path(record_a["directory"]) / "control.json").write_text(json.dumps(control_b))
    status = Path(record_a["directory"]) / "status.json"
    status.write_text(
        json.dumps(
            {
                **json.loads(status.read_text()),
                **{key: record_b[key] for key in ("id", "taskenv", "directory", "delegated")},
            }
        )
    )
    assert a.dispatch(request(a, "inspect"))["id"] == record_a["id"]
    assert a.dispatch(request(a, "stop"))["state"] == "stopped"
    still_running = b.dispatch(request(b, "inspect"))
    assert still_running["state"] == "running" and still_running["pid"] == record_b["pid"]
    assert registry.get("service", record_a["id"])["taskenv"] == a.task["id"]


def test_unauthenticated_service_control_does_not_stop_the_child(grants: Any) -> None:
    _, a, _ = grants
    record = start(a)
    handle = json.loads(Path(record["delegated"]["control_file"]).read_text())
    payloads = (
        b"[]",
        b"[" * 1500 + b"]" * 1500,
        json.dumps({"token": "錯誤", "action": "stop"}).encode(),
        b'{"action":"stop"}',
    )
    for payload in payloads:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(1)
            connection.connect(handle["socket"])
            connection.sendall(payload)
            assert connection.recv(1024) == b""
        observed = a.dispatch(request(a, "inspect"))
        assert observed["state"] == "running" and observed["pid"] == record["pid"]


def test_deeply_nested_status_cannot_crash_the_controller(grants: Any) -> None:
    _, a, _ = grants
    record = start(a)
    status = Path(record["directory"]) / "status.json"
    saved = status.read_bytes()
    try:
        status.write_bytes(b"[" * 1500 + b"]" * 1500)
        assert a.dispatch(request(a, "inspect"))["state"] == "running"
    finally:
        status.write_bytes(saved)
    assert a.dispatch(request(a, "stop"))["state"] == "stopped"


@pytest.mark.parametrize("state", ["stopped", "exited", "failed"])
def test_worker_terminal_files_cannot_stop_replace_or_remove_a_live_launch(
    grants: Any, state: str
) -> None:
    registry, a, b = grants
    record, peer = start(a), start(b)
    status = Path(record["directory"]) / "status.json"
    forged = {"state": state, "observed_at": "forged", "exit_code": 0}
    status.write_text(json.dumps({**forged, "terminal": forged, "terminal_acknowledged": True}))
    assert a.dispatch(request(a, "inspect"))["state"] == "running"
    assert "terminal" not in registry.get("service", record["id"])
    with pytest.raises(ManagementError, match="Service is running"):
        a.dispatch(request(a, "start"))
    assert registry.get("service", record["id"])["delegated"] == record["delegated"]
    with pytest.raises(ManagementError) as blocked:
        worktrees.remove(registry, a.task, yes=True, force=True)
    assert blocked.value.code == "services_remaining"
    revoke(registry, a.identity)
    stopped = services.stop(registry, a.task["id"], "job")
    assert stopped["state"] == "stopped" and stopped["terminal_acknowledged"]
    assert services.refresh(registry.get("service", record["id"]))["state"] == "stopped"
    observed_peer = b.dispatch(request(b, "inspect"))
    assert observed_peer["state"] == "running" and observed_peer["pid"] == peer["pid"]


def test_unverifiable_terminal_file_preserves_unknown_launch(grants: Any) -> None:
    registry, a, _ = grants
    record = start(a)
    status = Path(record["directory"]) / "status.json"
    status.write_text(json.dumps({"state": "stopped", "observed_at": "forged"}))
    handle = json.loads(Path(record["delegated"]["control_file"]).read_text())
    endpoint = Path(handle["socket"])
    saved = endpoint.with_suffix(".saved")
    endpoint.rename(saved)
    try:
        assert a.dispatch(request(a, "inspect"))["state"] == "unknown"
        with pytest.raises(ManagementError, match="unknown"):
            a.dispatch(request(a, "start"))
        with pytest.raises(ManagementError):
            services.stop(registry, a.task["id"], "job")
        preserved = registry.get("service", record["id"])
        assert preserved["state"] == "unknown" and "terminal" not in preserved
        assert preserved["delegated"] == record["delegated"]
    finally:
        saved.rename(endpoint)


def test_terminal_supervisor_waits_for_durable_manager_receipt(
    grants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, a, _ = grants
    record = start(a)
    assert services.record_control(record, "ack_terminal")["state"] == "running"
    os.kill(record["pid"], signal.SIGTERM)  # Only this fixture's freshly launched child.
    deadline = time.monotonic() + 3
    while services.record_control(record, "inspect")["state"] not in {"exited", "failed"}:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert services.refresh(record)["state"] == "exited"
    assert "terminal" not in registry.get("service", record["id"])
    # An early ACK cannot release the terminal evidence; file edits cannot replace it.
    (Path(record["directory"]) / "status.json").write_text("{}")
    original_put = registry.put

    def fail_receipt(kind: str, value: dict[str, Any]) -> None:
        if kind == "service" and "terminal" in value:
            raise OSError("Fixture receipt failure")
        original_put(kind, value)

    with monkeypatch.context() as patch:
        patch.setattr(registry, "put", fail_receipt)
        with pytest.raises(OSError, match="receipt failure"):
            services.stop(registry, a.task["id"], "job")
    assert services.record_control(record, "inspect")["state"] == "exited"
    stopped = services.stop(registry, a.task["id"], "job")
    assert stopped["terminal"]["state"] == "exited" and stopped["terminal_acknowledged"]
    deadline = time.monotonic() + 3
    while True:
        try:
            services.record_control(record, "inspect")
        except ManagementError:
            break
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert services.refresh(registry.get("service", record["id"]))["state"] == "exited"
    replacement = start(a)
    assert replacement["delegated"]["launch"] != record["delegated"]["launch"]


def test_acknowledgement_failure_keeps_the_recorded_terminal_result(
    grants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, a, _ = grants
    record = start(a)
    original = services.record_control

    def reject_ack(value: dict[str, Any], action: str) -> dict[str, Any]:
        if action == "ack_terminal":
            raise ManagementError("unknown_service", "Fixture ACK failure")
        return original(value, action)

    with monkeypatch.context() as patch:
        patch.setattr(services, "record_control", reject_ack)
        stopped = services.stop(registry, a.task["id"], "job")
    assert "unconfirmed" in stopped["warning"]
    stored = registry.get("service", record["id"])
    assert stored["terminal"]["state"] == "stopped" and not stored.get("terminal_acknowledged")
    assert original(record, "inspect")["state"] == "stopped"
    assert services.stop(registry, a.task["id"], "job")["terminal_acknowledged"]


@pytest.mark.parametrize("caller", ["delegated", "manager-revoked", "manager-closed"])
def test_restart_preserves_multiple_pending_acks_and_retry_does_not_stop_current_or_peer(
    grants: Any, monkeypatch: pytest.MonkeyPatch, caller: str
) -> None:
    registry, a, b = grants
    old, peer = start(a), start(b)
    original = services.record_control

    def reject_ack(value: dict[str, Any], action: str) -> dict[str, Any]:
        if action == "ack_terminal":
            raise ManagementError("unknown_service", "Fixture ACK unavailable")
        return original(value, action)

    if caller == "manager-revoked":
        revoke(registry, a.identity)
    elif caller == "manager-closed":
        a.close()
    with monkeypatch.context() as patch:
        patch.setattr(services, "record_control", reject_ack)
        services.stop(registry, a.task["id"], "job")
        services.stop(registry, b.task["id"], "job")
        peer_current = start(b)
        # Keep an additional receipt in another service scope; retry must not touch it.
        foreign = {
            **registry.get(services.TERMINAL_KIND, old["delegated"]["launch"]),
            "id": "other-service-receipt",
            "name": "other",
        }
        registry.put(services.TERMINAL_KIND, foreign)
        if caller == "delegated":
            second = start(a)
            services.stop(registry, a.task["id"], "job")
            current = start(a)
            expected = {old["delegated"]["launch"], second["delegated"]["launch"]}
        else:
            current = services.start(registry, a.task, "job")
            expected = {old["delegated"]["launch"]}
        assert set(current["pending_acks"]) == expected and "unconfirmed" in current["warning"]
        listed = services.list_services(registry, a.task["id"])[0]
        assert set(listed["pending_acks"]) == expected
        assert set(services.logs(registry, a.task["id"], "job")["pending_acks"]) == expected
        partial = services.retry_acks(registry, a.task["id"], "job")
        assert partial["acknowledged"] == [] and set(partial["pending_acks"]) == expected
    assert original(old, "inspect")["state"] == "stopped"
    attempted = []
    failed_once = False
    first_id = min(expected)

    def observe_retry(value: dict[str, Any], action: str) -> dict[str, Any]:
        nonlocal failed_once
        assert action == "ack_terminal" and value["id"] in expected
        attempted.append(value["id"])
        if caller == "delegated" and value["id"] == first_id and not failed_once:
            failed_once = True
            raise ManagementError("unknown_service", "Fixture partial retry failure")
        return original(value, action)

    with monkeypatch.context() as patch:
        patch.setattr(services, "record_control", observe_retry)
        retried = services.retry_acks(registry, a.task["id"], "job")
        if caller == "delegated":
            assert retried["pending_acks"] == [first_id]
            assert set(retried["acknowledged"]) == expected - {first_id}
            assert "warning" in retried
            retried = services.retry_acks(registry, a.task["id"], "job")
            assert retried["acknowledged"] == [first_id]
        else:
            assert set(retried["acknowledged"]) == expected
        assert retried["pending_acks"] == []
        assert services.retry_acks(registry, a.task["id"], "job")["acknowledged"] == []
    assert set(attempted) == expected
    fresh = services.list_services(registry, a.task["id"])[0]
    assert fresh["state"] == "running" and fresh["pid"] == current["pid"]
    assert "pending_acks" not in fresh and "warning" not in fresh
    for launch_id in expected:
        assert registry.get(services.TERMINAL_KIND, launch_id)["terminal_acknowledged"]
    # Neither a peer taskenv nor a different service can be acknowledged by this retry.
    assert not registry.get(services.TERMINAL_KIND, peer["delegated"]["launch"]).get(
        "terminal_acknowledged"
    )
    assert original(peer, "inspect")["state"] == "stopped"
    refreshed_peer = services.refresh(registry.get("service", peer_current["id"]))
    assert refreshed_peer["state"] == "running" and refreshed_peer["pid"] == peer_current["pid"]
    assert not registry.get(services.TERMINAL_KIND, foreign["id"]).get("terminal_acknowledged")
    registry.delete(services.TERMINAL_KIND, foreign["id"])


def test_independent_receipt_write_failure_prevents_ack_and_restart(
    grants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, a, _ = grants
    old = start(a)
    original_put = registry.put

    def fail_archive(kind: str, value: dict[str, Any]) -> None:
        if kind == services.TERMINAL_KIND:
            raise OSError("Fixture independent receipt failure")
        original_put(kind, value)

    with monkeypatch.context() as patch:
        patch.setattr(registry, "put", fail_archive)
        for operation in (
            lambda: services.stop(registry, a.task["id"], "job"),
            lambda: a.dispatch(request(a, "start")),
            lambda: services.start(registry, a.task, "job"),
        ):
            with pytest.raises(OSError, match="independent receipt failure"):
                operation()
            assert registry.get("service", old["id"])["delegated"] == old["delegated"]
            assert services.record_control(old, "inspect")["state"] == "stopped"
    assert services.stop(registry, a.task["id"], "job")["terminal_acknowledged"]


def test_retry_can_collect_a_receipt_without_a_current_service_row(
    grants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, a, _ = grants
    old = start(a)
    original = services.record_control
    with monkeypatch.context() as patch:

        def reject_ack(value: dict[str, Any], action: str) -> dict[str, Any]:
            if action == "ack_terminal":
                raise ManagementError("unknown_service", "Fixture ACK unavailable")
            return original(value, action)

        patch.setattr(services, "record_control", reject_ack)
        services.stop(registry, a.task["id"], "job")
    registry.delete("service", old["id"])
    result = services.retry_acks(registry, a.task["id"], "job")
    assert result["acknowledged"] == [old["delegated"]["launch"]] and result["pending_acks"] == []


def test_confirmed_receipt_survives_failure_to_update_current_service(
    grants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, a, _ = grants
    old = start(a)
    original_put = registry.put

    def fail_current_confirmation(kind: str, value: dict[str, Any]) -> None:
        if kind == "service" and value.get("terminal_acknowledged"):
            raise OSError("Fixture current confirmation failure")
        original_put(kind, value)

    with monkeypatch.context() as patch:
        patch.setattr(registry, "put", fail_current_confirmation)
        with pytest.raises(OSError, match="current confirmation failure"):
            services.stop(registry, a.task["id"], "job")
    receipt = registry.get(services.TERMINAL_KIND, old["delegated"]["launch"])
    assert receipt["terminal_acknowledged"]
    with monkeypatch.context() as patch:
        patch.setattr(
            services, "record_control", lambda *_: pytest.fail("Retried an already confirmed ACK")
        )
        stopped = services.stop(registry, a.task["id"], "job")
    assert stopped["terminal_acknowledged"] and "pending_acks" not in stopped


def test_lost_ack_reply_remains_pending_without_blocking_replacement(
    grants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, a, _ = grants
    old = start(a)
    original = services.record_control

    def lose_reply(value: dict[str, Any], action: str) -> dict[str, Any]:
        response = original(value, action)
        if action == "ack_terminal":
            raise ManagementError("unknown_service", "Fixture ACK reply lost")
        return response

    with monkeypatch.context() as patch:
        patch.setattr(services, "record_control", lose_reply)
        stopped = services.stop(registry, a.task["id"], "job")
    launch_id = old["delegated"]["launch"]
    assert stopped["pending_acks"] == [launch_id]
    current = start(a)
    assert current["state"] == "running" and current["pending_acks"] == [launch_id]
    # Even though the old supervisor exited, absence is not a confirmation.
    result = services.retry_acks(registry, a.task["id"], "job")
    assert result["acknowledged"] == [] and result["pending_acks"] == [launch_id]
    assert not registry.get(services.TERMINAL_KIND, launch_id).get("terminal_acknowledged")
    observed = services.refresh(registry.get("service", current["id"]))
    assert observed["state"] == "running" and observed["pid"] == current["pid"]


def test_missing_checkout_delegation_requires_manager_stop(grants: Any) -> None:
    registry, a, _ = grants
    record = start(a)
    root = Path(a.task["path"])
    moved = root.with_name(root.name + "-moved")
    root.rename(moved)
    try:
        with pytest.raises(ManagementError) as missing:
            a.dispatch(request(a, "stop"))
        assert missing.value.code == "missing"
        assert services.record_control(record, "inspect")["state"] == "running"
        assert services.stop(registry, a.task["id"], "job")["state"] == "stopped"
    finally:
        moved.rename(root)


def test_issued_launch_can_finish_after_revoke_and_remains_manageable(grants: Any) -> None:
    registry, a, _ = grants
    prepared = a.dispatch(request(a, "start"))
    revoke(registry, a.identity)
    assert services.launch(prepared["record"], prepared["payload"])["state"] == "running"
    with pytest.raises(ManagementError) as inactive:
        a.dispatch(request(a, "inspect"))
    assert inactive.value.code == "delegation_revoked"
    assert services.stop(registry, a.task["id"], "job")["terminal_acknowledged"]


def test_failed_delegated_start_keeps_its_terminal_result_until_recorded(grants: Any) -> None:
    registry, a, _ = grants
    a.close()
    recipe = Path(a.task["path"]) / CONFIG
    recipe.write_text(
        recipe.read_text()
        .replace(
            json.dumps([sys.executable, "-c", "pass"]),
            json.dumps([sys.executable, "-c", "raise SystemExit(1)"]),
        )
        .replace("ready_timeout=3", "ready_timeout=0.2")
    )
    controller = Controller(registry, a.task, ["job"])
    try:
        prepared = controller.dispatch(request(controller, "start"))
        assert services.launch(prepared["record"], prepared["payload"])["state"] == "failed"
        assert "terminal" not in registry.get("service", prepared["record"]["id"])
        failed = controller.dispatch(request(controller, "inspect"))
        assert failed["state"] == "failed" and failed["terminal_acknowledged"]
        assert failed["error"] == "readiness_timeout"
        assert services.refresh(registry.get("service", failed["id"]))["state"] == "failed"
    finally:
        controller.close()


def test_repointed_service_socket_cannot_stop_a_peer(grants: Any) -> None:
    _, a, b = grants
    record_a, record_b = start(a), start(b)
    socket_a = Path(json.loads(Path(record_a["delegated"]["control_file"]).read_text())["socket"])
    socket_b = Path(json.loads(Path(record_b["delegated"]["control_file"]).read_text())["socket"])
    saved = socket_a.with_suffix(".saved")
    socket_a.rename(saved)
    socket_a.symlink_to(socket_b)
    try:
        with pytest.raises(ManagementError):
            a.dispatch(request(a, "stop"))
        observed = b.dispatch(request(b, "inspect"))
        assert observed["state"] == "running" and observed["pid"] == record_b["pid"]
    finally:
        socket_a.unlink()
        saved.rename(socket_a)


def test_stale_launch_cannot_replace_a_current_observation(grants: Any) -> None:
    _, a, _ = grants
    record = start(a)
    with pytest.raises(ManagementError, match="replaced"):
        a.dispatch(request(a, "stop", launch="0" * 32))
    assert a.dispatch(request(a, "inspect"))["pid"] == record["pid"]


@pytest.mark.parametrize("attack", ["symlink", "hardlink", "parent", "fifo"])
def test_manager_never_follows_worker_log_paths_outside_its_runtime(
    grants: Any,
    attack: str,
) -> None:
    _, a, b = grants
    result = a.dispatch(request(a, "start"))
    directory = Path(result["record"]["directory"])
    directory.mkdir(parents=True)
    outside = Path(b.runtime["root"]) / "output.log"
    outside.write_text("other-task-private-fixture")
    log = directory / "output.log"
    if attack == "symlink":
        log.symlink_to(outside)
    elif attack == "hardlink":
        os.link(outside, log)
    elif attack == "parent":
        directory.rmdir()
        directory.symlink_to(outside.parent, target_is_directory=True)
    else:
        os.mkfifo(log)
    with pytest.raises((OSError, ManagementError)):
        a.dispatch(request(a, "logs"))
    assert outside.read_text() == "other-task-private-fixture"


def test_manager_start_reservation_does_not_write_worker_owned_paths(grants: Any) -> None:
    _, a, b = grants
    runs = Path(a.runtime["root"]) / "runs"
    outside = Path(b.runtime["root"]) / "unrelated"
    outside.mkdir()
    runs.symlink_to(outside, target_is_directory=True)
    a.dispatch(request(a, "start"))
    assert list(outside.iterdir()) == []


def test_replaced_taskenv_or_runtime_identity_invalidates_the_grant(grants: Any) -> None:
    _, a, _ = grants
    runtime = Path(a.runtime["root"])
    runtime.rename(runtime.with_name(runtime.name + "-previous"))
    runtime.mkdir()
    with pytest.raises(ManagementError, match="replaced"):
        a.dispatch(request(a, "list"))
