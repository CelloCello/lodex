from __future__ import annotations

import json
import sqlite3
import stat
from pathlib import Path
from typing import Any

import pytest

from lodex_core.management.common import APPLICATION_ID, ManagementError
from lodex_core.management.project_config import CONFIG, load
from lodex_core.management.secrets import SQLiteSecrets
from lodex_core.management.store import SCHEMA_VERSION, Registry


def test_plaintext_roundtrip_reopen_and_permissions(registry: Registry) -> None:
    provider = SQLiteSecrets(registry)
    value = "fixture-'quoted'\n多行值"
    provider.set("secret:shared", value)
    assert registry.db.execute("SELECT value FROM secrets").fetchone()[0] == value
    assert stat.S_IMODE(registry.root.stat().st_mode) == 0o700
    assert stat.S_IMODE(registry.path.stat().st_mode) == 0o600
    reader = Registry(registry.root, read_only=True)
    try:
        assert SQLiteSecrets(reader).get("secret:shared") == value
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            SQLiteSecrets(reader).set("secret:shared", "rejected")
        assert provider.get("secret:shared") == value
    finally:
        reader.close()
    provider.set("secret:shared", "replacement")
    assert provider.get("secret:shared") == "replacement"
    provider.remove("secret:shared")
    provider.remove("secret:shared")
    with pytest.raises(ManagementError, match="Secret is not set"):
        provider.get("secret:shared")
    assert sorted(p.name for p in registry.root.iterdir()) == ["management.db"]


@pytest.mark.parametrize("value", ["", "invalid\x00value"])
def test_invalid_secret_does_not_overwrite(registry: Registry, value: str) -> None:
    provider = SQLiteSecrets(registry)
    provider.set("secret:fixture", "original")
    with pytest.raises(ManagementError, match=r"nonempty.*NUL"):
        provider.set("secret:fixture", value)
    assert provider.get("secret:fixture") == "original"


@pytest.mark.parametrize("reference", ["keychain:old", "plain-value", "secret:", "secret: "])
def test_reference_contract_at_config_and_storage(
    registry: Registry, repo: Path, reference: str
) -> None:
    with pytest.raises(ManagementError, match="reference"):
        SQLiteSecrets(registry).set(reference, "unused")
    (repo / CONFIG).write_text(f'schema_version=1\n[secrets]\nTOKEN="{reference}"\n')
    with pytest.raises(ManagementError, match="reference"):
        load(repo / CONFIG)
    assert not registry.db.execute("SELECT * FROM secrets").fetchall()


@pytest.mark.parametrize("version", [1, 2])
def test_upgrade_removes_overrides_preserves_secrets_and_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: int
) -> None:
    root = tmp_path / "old-manager"
    root.mkdir(mode=0o755)
    path = root / "management.db"
    record = {
        "id": "legacy",
        "ports": {"PORT": 24000},
        "settings": {"APP_MODE": "old-override"},
        "secret_refs": {"TOKEN": "secret:shared"},
    }
    other_record = {"id": "old-operation", "state": "succeeded"}
    connect = sqlite3.connect
    with connect(path) as db:
        db.execute("CREATE TABLE records(kind TEXT,id TEXT,data TEXT,PRIMARY KEY(kind,id))")
        db.execute("INSERT INTO records VALUES(?,?,?)", ("taskenv", "legacy", json.dumps(record)))
        db.execute(
            "INSERT INTO records VALUES(?,?,?)",
            ("operation", other_record["id"], json.dumps(other_record)),
        )
        if version == 2:
            db.execute("CREATE TABLE secrets(reference TEXT PRIMARY KEY,value TEXT NOT NULL)")
            db.execute("INSERT INTO secrets VALUES(?,?)", ("secret:shared", "preserved-fixture"))
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute(f"PRAGMA user_version={version}")
    path.chmod(0o644)
    before = path.read_bytes()
    with pytest.raises(ManagementError, match="writable command"):
        Registry(root, read_only=True)
    assert path.read_bytes() == before

    class FailMigration(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            if sql == f"PRAGMA user_version={SCHEMA_VERSION}":
                raise sqlite3.OperationalError("injected migration failure")
            return super().execute(sql, parameters)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", lambda *a, **kw: connect(*a, **kw, factory=FailMigration))
        with pytest.raises(sqlite3.OperationalError, match="injected"):
            Registry(root)
    with connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == version
        if version == 1:
            assert not db.execute("SELECT name FROM sqlite_master WHERE name='secrets'").fetchall()
        else:
            assert db.execute("SELECT value FROM secrets").fetchone()[0] == "preserved-fixture"
        assert (
            json.loads(db.execute("SELECT data FROM records WHERE kind='taskenv'").fetchone()[0])
            == record
        )
    upgraded = Registry(root)
    try:
        assert upgraded.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert upgraded.get("taskenv", "legacy") == {"id": "legacy", "ports": {"PORT": 24000}}
        assert upgraded.get("operation", "old-operation") == other_record
        if version == 2:
            assert SQLiteSecrets(upgraded).get("secret:shared") == "preserved-fixture"
        SQLiteSecrets(upgraded).set("secret:new", "fixture-value")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
    finally:
        upgraded.close()
