"""Independent SQLite registry and advisory locks for local operations."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from lodex_core.management.common import APPLICATION_ID, ManagementError, name, private_dir

SCHEMA_VERSION = 3


class Registry:
    def __init__(self, root: Path | None = None, *, read_only: bool = False) -> None:
        self.root = (root or Path(os.environ.get("LODEX_HOME", "~/.lodex"))).expanduser().resolve()
        self.path = self.root / "management.db"
        if read_only:
            if not self.path.is_file():
                raise ManagementError(
                    "not_found", "No management registry; register a project first"
                )
            self.db = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)
            self.db.row_factory = sqlite3.Row
            if (
                self.db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                or self.db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
            ):
                self.db.close()
                raise ManagementError(
                    "wrong_database",
                    "Unsupported management registry; use a writable command to upgrade older data",
                )
            return
        private_dir(self.root)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.row_factory = sqlite3.Row
        try:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                app = self.db.execute("PRAGMA application_id").fetchone()[0]
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
                tables = self.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                if app != APPLICATION_ID and (app or version or tables):
                    raise ManagementError(
                        "wrong_database", "Management refuses a non-management DB"
                    )
                if version not in (0, 1, 2, SCHEMA_VERSION):
                    raise ManagementError(
                        "schema_version", "Unsupported management database version"
                    )
                if version == 0:
                    self.db.execute(
                        "CREATE TABLE records (kind TEXT, id TEXT, data TEXT NOT NULL, "
                        "PRIMARY KEY(kind,id))"
                    )
                    self.db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                # Tighten existing databases too, before they can hold plaintext secrets.
                self.path.chmod(0o600)
                if version < 2:
                    self.db.execute(
                        "CREATE TABLE secrets (reference TEXT PRIMARY KEY, value TEXT NOT NULL)"
                    )
                if version < 3:
                    for row in self.db.execute(
                        "SELECT id, data FROM records WHERE kind='taskenv'"
                    ).fetchall():
                        record = json.loads(row["data"])
                        record.pop("settings", None)
                        record.pop("secret_refs", None)
                        self.db.execute(
                            "UPDATE records SET data=? WHERE kind='taskenv' AND id=?",
                            (json.dumps(record), row["id"]),
                        )
                    self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        except BaseException:
            self.db.close()
            raise

    def close(self) -> None:
        self.db.close()

    def all(self, kind: str) -> list[dict[str, Any]]:
        return [
            json.loads(row[0])
            for row in self.db.execute("SELECT data FROM records WHERE kind=? ORDER BY id", (kind,))
        ]

    def get(self, kind: str, identity: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT data FROM records WHERE kind=? AND id=?", (kind, identity)
        ).fetchone()
        if row is None:
            raise ManagementError("not_found", f"Unknown {kind}: {identity}")
        result: dict[str, Any] = json.loads(row[0])
        return result

    def put(self, kind: str, record: dict[str, Any]) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) "
                "DO UPDATE SET data=excluded.data",
                (kind, record["id"], json.dumps(record)),
            )

    def delete(self, kind: str, identity: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, identity))

    def reload_task(self, task: dict[str, Any]) -> None:
        current = self.get("taskenv", task["id"])
        task.clear()
        task.update(current)

    def busy(self, key: str) -> bool:
        path = self.root / "locks" / name(key)
        if not path.exists():
            return False
        with path.open("r") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(stream, fcntl.LOCK_UN)
        return False

    @contextmanager
    def lock(self, key: str) -> Generator[None, None, None]:
        private_dir(self.root / "locks")
        with (self.root / "locks" / name(key)).open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ManagementError("busy", f"Another operation holds {key}") from exc
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
