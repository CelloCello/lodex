"""Standalone test application: SQLite data, an HTTP queue, and a local worker."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote


def context() -> tuple[Path, dict[str, str]]:
    root = Path(os.environ["LODEX_WORKTREE"]).resolve()
    identity = os.environ["LODEX_TASKENV_ID"]
    if root != Path.cwd().resolve() or not re.fullmatch(r"[a-z0-9_-]{1,64}", identity):
        raise ValueError("Run inside the explicitly selected taskenv")
    directory = root / ".lodex/state"
    if root not in directory.resolve().parents or directory.is_symlink():
        raise ValueError("Fixture state must stay inside this checkout")
    return directory, {"taskenv": identity, "path": str(root)}


def owned(directory: Path, owner: dict[str, str]) -> None:
    if json.loads((directory / "owner.json").read_text()) != owner:
        raise ValueError("Fixture resource owner does not match this taskenv")


def report(directory: Path, state: str) -> None:
    result = os.environ.get("LODEX_RESULT_FILE")
    if result:
        Path(result).write_text(
            json.dumps(
                {
                    "resources": [
                        {
                            "name": name,
                            "kind": "sqlite",
                            "id": str(directory / f"{name}.sqlite3"),
                            "scope": "exclusive",
                            "state": state,
                        }
                        for name in ("data", "queue")
                    ]
                }
            )
        )


def serve(directory: Path, role: str) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def respond(self, payload: Any, status: int = 200) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def handle_request(self, write: bool) -> None:
            if self.headers.get("Authorization") != f"Bearer {os.environ['API_TOKEN']}":
                self.respond({"error": "unauthorized"}, 401)
                return
            if self.path == "/health":
                self.respond({"taskenv": os.environ["LODEX_TASKENV_ID"], "role": role})
                return
            payload = (
                json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if write
                else {}
            )
            if role == "api" and self.path.startswith("/values/"):
                key = unquote(self.path.removeprefix("/values/"))
                with sqlite3.connect(directory / "data.sqlite3") as db:
                    if write:
                        db.execute(
                            "INSERT OR REPLACE INTO values_store VALUES (?,?)",
                            (key, payload["value"]),
                        )
                    row = db.execute(
                        "SELECT value FROM values_store WHERE key=?", (key,)
                    ).fetchone()
                self.respond({"value": row[0] if row else None})
            elif role == "queue" and self.path == "/items":
                with sqlite3.connect(directory / "queue.sqlite3") as db:
                    if write:
                        db.execute(
                            "INSERT INTO items(value,done) VALUES (?,0)", (payload["value"],)
                        )
                    rows = db.execute("SELECT value,done FROM items ORDER BY id").fetchall()
                self.respond({"items": [{"value": row[0], "done": bool(row[1])} for row in rows]})
            else:
                self.respond({"error": "not_found"}, 404)

        def do_GET(self) -> None:
            self.handle_request(False)

        def do_POST(self) -> None:
            self.handle_request(True)

    port = int(os.environ["API_PORT" if role == "api" else "QUEUE_PORT"])
    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"{role} ready", flush=True)
        server.serve_forever()


def main(action: str) -> None:
    directory, owner = context()
    if action == "prepare":
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / "owner.json"
        if marker.exists():
            owned(directory, owner)
        else:
            marker.write_text(json.dumps(owner))
        with sqlite3.connect(directory / "data.sqlite3") as db:
            db.execute("CREATE TABLE IF NOT EXISTS values_store(key TEXT PRIMARY KEY,value TEXT)")
        with sqlite3.connect(directory / "queue.sqlite3") as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY,value TEXT,done INTEGER)"
            )
        report(directory, "present")
    elif action == "verify":
        owned(directory, owner)
        for filename, table in (("data", "values_store"), ("queue", "items")):
            with sqlite3.connect(
                f"{(directory / f'{filename}.sqlite3').as_uri()}?mode=ro", uri=True
            ) as db:
                db.execute(f"SELECT count(*) FROM {table}")
        report(directory, "present")
    elif action == "cleanup":
        owned(directory, owner)
        shutil.rmtree(directory)
        report(directory, "removed")
    elif action in ("api", "queue"):
        owned(directory, owner)
        serve(directory, action)
    elif action == "worker":
        owned(directory, owner)
        print("worker ready", flush=True)
        while True:
            with sqlite3.connect(directory / "queue.sqlite3") as queue:
                item = queue.execute(
                    "SELECT id,value FROM items WHERE done=0 ORDER BY id LIMIT 1"
                ).fetchone()
                if item:
                    with sqlite3.connect(directory / "data.sqlite3") as db:
                        db.execute(
                            "INSERT OR REPLACE INTO values_store VALUES (?,?)",
                            (f"processed:{item[1]}", item[1]),
                        )
                    queue.execute("UPDATE items SET done=1 WHERE id=?", (item[0],))
                    print(f"processed item {item[0]}", flush=True)
            time.sleep(0.05)
    else:
        raise ValueError("Unknown fixture command")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except (KeyError, ValueError, OSError, sqlite3.Error) as exc:
        print(f"Fixture command failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
