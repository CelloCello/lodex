from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from lodex_console.actions import Action, detail, execute
from lodex_console.app import create_app
from lodex_core.management import worktrees
from lodex_core.management.project_config import CONFIG
from lodex_core.management.secrets import SQLiteSecrets
from lodex_core.management.store import Registry


def client(root: Path) -> TestClient:
    return TestClient(
        create_app(root, "fixture-token", 8765),
        base_url="http://127.0.0.1:8765",
        headers={"Authorization": "Bearer fixture-token", "Origin": "http://127.0.0.1:8765"},
    )


def post(api: TestClient, **fields: Any) -> dict[str, Any]:
    response = api.post("/api/action", json=fields)
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    assert payload["ok"], payload
    return dict(payload["result"])


def test_empty_console_is_read_only_and_requires_local_auth(tmp_path: Path) -> None:
    root = tmp_path / "absent"
    with client(root) as api:
        assert api.get("/api/state").json()["result"] == {
            "projects": [],
            "taskenvs": [],
            "secrets": [],
        }
        assert not root.exists()
        assert api.get("/api/state", headers={"Authorization": ""}).status_code == 401
        assert api.get("/api/state", headers={"Host": "attacker.example"}).status_code == 403
        assert api.get("/api/state", headers={"Origin": "https://evil.example"}).status_code == 403
        response = api.post(
            "/api/action",
            json={"action": "secret.set", "name": "x", "value": "x"},
            headers={"Origin": "null"},
        )
        assert response.status_code == 403 and not root.exists()
        assert api.get("/openapi.json").status_code == 404


def test_project_names_and_duplicate_links_cross_worker_boundary(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktrees.git(repo, "init", "-q")
    with client(tmp_path / "registry") as api:
        original = post(
            api, action="project.add", name="stable", path=str(repo), display_name="Original"
        )
        renamed = post(api, action="project.rename", project="stable", display_name="新的專案")
        assert renamed["id"] == "stable" and renamed["display_name"] == "新的專案"
        assert renamed["source"] == original["source"]
        assert api.get("/api/state").json()["result"]["projects"] == [renamed]
        duplicate = api.post(
            "/api/action", json={"action": "project.add", "name": "other", "path": str(repo)}
        ).json()
        assert not duplicate["ok"]
        assert duplicate["error"]["details"] == {"existing_project": "stable"}
        unchanged = post(
            api, action="project.add", name="stable", path=str(repo), display_name="Ignored"
        )
        assert unchanged["already_registered"]
        assert unchanged["display_name"] == "新的專案"
        pinned = post(api, action="project.pin", project="stable")
        assert pinned["pinned"] is True
        assert api.get("/api/state").json()["result"]["projects"][0]["pinned"] is True
        preview = post(api, action="project.delete", project="stable")
        assert not preview["removed"]
        assert len(api.get("/api/state").json()["result"]["projects"]) == 1
        post(api, action="worktree.attach", project="stable", path=str(repo))
        blocked = api.post(
            "/api/action", json={"action": "project.delete", "project": "stable", "yes": True}
        ).json()
        assert blocked["error"]["code"] == "project_not_empty"


def test_secret_submission_never_echoed_even_on_invalid_input(tmp_path: Path) -> None:
    with client(tmp_path / "state") as api:
        value = "synthetic-test-value"
        post(api, action="secret.set", name="shared", value=value)
        state = api.get("/api/state")
        assert state.json()["result"]["secrets"] == ["shared"]
        assert value not in state.text
        response = api.post("/api/action", json={"action": "shell", "value": value})
        assert response.status_code == 422 and value not in response.text
        response = api.post("/api/action", json={"action": "secret.set", "value": {"bad": value}})
        assert value not in response.text
        post(api, action="secret.remove", name="shared")
        assert api.get("/api/state").json()["result"]["secrets"] == ["shared"]
        post(api, action="secret.remove", name="shared", yes=True)
        assert api.get("/api/state").json()["result"]["secrets"] == []


def test_cli_core_to_console_operations_and_missing_checkout(
    registry: Registry, repo: Path
) -> None:
    (repo / CONFIG).write_text(
        "schema_version=1\n[commands.prepare]\nargv="
        + json.dumps([sys.executable, "-c", "print('prepared')"])
        + "\n[services.web]\nargv="
        + json.dumps([sys.executable, "-m", "http.server", "${PORT}", "--bind", "127.0.0.1"])
        + '\nready_port="PORT"\nurl="http://127.0.0.1:${PORT}"\n[ports]\nPORT=0\n'
    )
    worktrees.project_add(registry, "sample", repo, None)
    task = worktrees.attach(registry, "sample", repo, None)
    with client(registry.root) as api:
        info = api.get(f"/api/task/{task['id']}").json()["result"]
        assert info["commands"] == ["prepare"] and info["configured_services"] == ["web"]
        result = post(api, action="prepare", target=task["id"])
        assert result["state"] == "succeeded"
        logs = post(api, action="operation.logs", target=result["id"])
        assert "prepared" in logs["tail"]
        try:
            post(api, action="service.start", target=task["id"], name="web")
            from lodex_core.management import services

            assert services.list_services(registry, task["id"])[0]["state"] == "running"
            # Removing configuration must not make the actual service unmanageable.
            (repo / CONFIG).unlink()
            info = api.get(f"/api/task/{task['id']}").json()["result"]
            assert info["configuration_error"] and info["services"][0]["state"] == "running"
        finally:
            post(api, action="service.stop", target=task["id"], name="web")
        preview = post(api, action="worktree.remove", target=task["id"])
        assert preview["main"] and "git_status" in preview
        response = api.post(
            "/api/action", json={"action": "worktree.remove", "target": task["id"], "yes": True}
        )
        assert response.json()["error"]["code"] == "protected_checkout"
        preview = post(api, action="worktree.forget", target=task["id"])
        assert preview["id"] == task["id"] and "forgotten" not in preview
        assert "does not stop services" in preview["warning"]
        assert registry.get("taskenv", task["id"])["id"] == task["id"]
        result = post(api, action="worktree.forget", target=task["id"], yes=True)
        assert result["forgotten"] is True and result["id"] == task["id"]
        assert result["warning"] == preview["warning"]
        assert repo.exists() and registry.all("taskenv") == []


def test_console_target_is_explicit_and_locks_are_shared(registry: Registry, repo: Path) -> None:
    worktrees.project_add(registry, "sample", repo, None)
    task = worktrees.attach(registry, "sample", repo, None)
    with client(registry.root) as api:
        response = api.post("/api/action", json={"action": "prepare"})
        assert response.json()["error"]["code"] == "invalid_input"
        with registry.lock(task["id"]):
            response = api.post("/api/action", json={"action": "prepare", "target": task["id"]})
        assert response.json()["error"]["code"] == "busy"
        response = api.post(
            "/api/action", json={"action": "project.add", "name": "bad", "path": "."}
        )
        assert response.json()["error"]["code"] == "invalid_input"


def test_detail_and_forget_preserve_secret(registry: Registry, repo: Path) -> None:
    worktrees.project_add(registry, "sample", repo, None)
    task = worktrees.attach(registry, "sample", repo, None)
    SQLiteSecrets(registry).set("secret:shared", "test-value")
    (repo / CONFIG).write_text("broken TOML")
    assert detail(registry.root, task["id"])["configuration_error"]["code"] == "config_unavailable"
    execute(registry, Action(action="worktree.forget", target=task["id"], yes=True))
    assert SQLiteSecrets(registry).get("secret:shared") == "test-value"


def test_legacy_external_is_visible_but_cannot_be_controlled(
    registry: Registry, repo: Path
) -> None:
    worktrees.project_add(registry, "sample", repo, None)
    task = worktrees.attach(registry, "sample", repo, None)
    record = {
        "id": f"{task['id']}-old-api",
        "taskenv": task["id"],
        "name": "old-api",
        "state": "external",
        "url": "https://example.invalid",
    }
    registry.put("service", record)
    (repo / CONFIG).write_text(
        'schema_version=1\n[services.old-api]\nexternal=true\nurl="https://example.invalid"\n'
    )
    with client(registry.root) as api:
        info = api.get(f"/api/task/{task['id']}").json()["result"]
        assert info["configuration_error"]["code"] == "invalid_config"
        assert "env/secrets" in info["configuration_error"]["message"]
        assert info["services"][0]["url"] == record["url"]
        assert "read-only" in info["services"][0]["warning"]
        overview = api.get("/api/state").json()["result"]
        assert overview["taskenvs"][0]["services"] == info["services"]
        for action in ("service.start", "service.stop", "service.logs"):
            result = api.post(
                "/api/action", json={"action": action, "target": task["id"], "name": "old-api"}
            ).json()
            assert result["ok"] is False and result["error"]["code"] == "legacy_service"
        assert registry.get("service", record["id"]) == record
