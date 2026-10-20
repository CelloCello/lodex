"""Ephemeral CLI-created environment for the console browser suite."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import uvicorn

from lodex_console.app import create_app
from lodex_core.management import services, worktrees
from lodex_core.management.store import Registry


def main() -> None:
    port = int(os.environ.get("LODEX_TEST_PORT", "18765"))
    with tempfile.TemporaryDirectory(prefix="lodex-browser-") as directory:
        root = Path(directory).resolve()
        repo = root / "repo"
        repo.mkdir()
        for args in (
            ("init", "-q"),
            ("config", "user.name", "Fixture"),
            ("config", "user.email", "fixture@example.invalid"),
        ):
            worktrees.git(repo, *args)
        (repo / "README.md").write_text("Browser fixture\n")
        (repo / ".lodex").mkdir()
        recipe = (
            "schema_version=1\n[ports]\nPORT=0\n"
            "[commands.prepare]\nargv="
            + json.dumps([sys.executable, "-c", "print('prepared fixture')"])
            + "\n[commands.verify]\nargv="
            + json.dumps([sys.executable, "-c", "print('verified')"])
            + "\n[commands.slow]\nargv="
            + json.dumps(
                [sys.executable, "-c", "import time; time.sleep(2); print('finished once')"]
            )
            + "\n[commands.cleanup]\nargv="
            + json.dumps([sys.executable, "-c", "print('cleaned')"])
            + "\n[services.http]\nargv="
            + json.dumps([sys.executable, "-m", "http.server", "${PORT}", "--bind", "127.0.0.1"])
            + '\nready_port="PORT"\nurl="http://127.0.0.1:${PORT}"\n'
        )
        (repo / ".lodex/project.toml").write_text(recipe)
        worktrees.git(repo, "add", ".")
        worktrees.git(repo, "commit", "-qm", "fixture")
        env = {**os.environ, "LODEX_HOME": str(root / "manager")}

        def cli(*args: str) -> dict[str, object]:
            result = subprocess.run(
                [sys.executable, "-m", "lodex_cli.main", *args, "--json"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            return dict(json.loads(result.stdout)["result"])

        cli("project", "add", "browser-fixture", str(repo))
        task = cli(
            "worktree", "create", "browser-fixture", "--ref", "HEAD", "--branch", "feature/console"
        )
        cli("service", "start", "http", "--target", str(task["id"]))
        store = Registry(root / "manager")
        try:
            uvicorn.run(
                create_app(store.root, "browser-fixture-token", port),
                host="127.0.0.1",
                port=port,
                access_log=False,
                proxy_headers=False,
            )
        finally:
            for record in store.all("service"):
                services.stop(store, record["taskenv"], record["name"])
            store.close()


if __name__ == "__main__":
    main()
