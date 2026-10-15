"""Build and exercise an installed wheel outside the source checkout."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout[-1500:] + result.stderr[-1500:])
    return result.stdout


def verify_isolation(root: Path, artifacts: Path, version: str, env: dict[str, str]) -> None:
    """Install each distribution with only its declared runtime dependencies."""
    for distribution, package, absent in (
        ("lodex_core", "lodex_core", ["lodex_cli", "lodex_console", "typer", "fastapi", "mcp"]),
        ("lodex_console", "lodex_console", ["lodex_cli", "typer", "mcp"]),
        ("lodex", "lodex_cli", ["lodex_console", "fastapi"]),
    ):
        environment = root / f"{distribution}-isolated"
        python = environment / "bin/python"
        run(["uv", "venv", str(environment), "--python", sys.executable], root, env)
        wheel = artifacts / f"{distribution}-{version}-py3-none-any.whl"
        run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--find-links",
                str(artifacts),
                str(wheel),
            ],
            root,
            env,
        )
        check = """
import importlib, importlib.util, json, pathlib, pkgutil, sys
package = importlib.import_module(sys.argv[1])
assert pathlib.Path(package.__file__).is_relative_to(sys.argv[2]), package.__file__
for module in pkgutil.walk_packages(package.__path__, package.__name__ + '.'):
    importlib.import_module(module.name)
for name in json.loads(sys.argv[3]):
    assert importlib.util.find_spec(name) is None, name
"""
        run([str(python), "-c", check, package, str(environment), json.dumps(absent)], root, env)
        if package == "lodex_console":
            check = """
import asyncio, pathlib, sys
import httpx
from lodex_console.app import create_app
async def check():
    app = create_app(pathlib.Path(sys.argv[1]), 'isolation-token', 8765)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
        base_url='http://127.0.0.1:8765', headers={
            'Authorization': 'Bearer isolation-token', 'Origin': 'http://127.0.0.1:8765',
        }) as client:
        response = await client.post('/api/action', json={
            'action': 'secret.set', 'name': 'isolated', 'value': 'synthetic-isolation-value',
        })
        assert response.status_code == 200 and response.json()['ok'], response.text
        response = await client.get('/api/state')
        assert response.json()['result']['secrets'] == ['isolated'], response.text
asyncio.run(check())
"""
            run([str(python), "-c", check, str(root / "isolated-server-state")], root, env)
        elif package == "lodex_cli":
            run([str(environment / "bin/lodex"), "--help"], root, env)
            check = """
import asyncio, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def check():
    params = StdioServerParameters(command=sys.executable, args=['-m', 'lodex_cli.main', 'mcp'])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.list_tools()
        assert {tool.name for tool in result.tools} == {'status', 'search', 'show'}
asyncio.run(check())
"""
            run([str(python), "-c", check], root, env)


def main() -> None:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    from lodex_cli import __version__

    with tempfile.TemporaryDirectory(prefix="lodex-distribution-") as directory:
        root = Path(directory).resolve()
        artifacts = root / "artifacts"
        run(["uv", "build", "--all-packages", "--out-dir", str(artifacts)], ROOT, env)
        # Rebuild each sdist outside the checkout, including the server without its frontend.
        rebuilt = root / "rebuilt"
        for source in sorted(artifacts.glob("*.tar.gz")):
            run(["uv", "build", str(source), "--wheel", "--out-dir", str(rebuilt)], root, env)
        assert len(list(rebuilt.glob("*.whl"))) == 3
        artifacts = rebuilt
        wheel = artifacts / f"lodex-{__version__}-py3-none-any.whl"
        python = root / "venv/bin/python"
        env["LODEX_HOME"] = str(root / "manager")
        env["LODEX_CONFIG"] = str(root / "absent-history.toml")
        verify_isolation(root, artifacts, __version__, env)
        run(["uv", "venv", str(root / "venv"), "--python", sys.executable], root, env)
        run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--find-links",
                str(artifacts),
                f"{wheel}[console]",
            ],
            root,
            env,
        )
        assert (
            run([str(python), "-m", "lodex_cli.main", "--version"], root, env).strip()
            == f"lodex {__version__}"
        )
        # Real bundled installation with only Path.home redirected in the test process.
        # Never repoint the user's HOME or write their global agent configuration.
        check = """
import json, pathlib, sys
from unittest.mock import patch
import lodex_cli
from lodex_cli.main import main
from lodex_core.management.store import Registry
from lodex_core.management.secrets import SQLiteSecrets
from lodex_cli.skill_install import SKILL_NAMES
root = pathlib.Path(sys.argv[1])
assert str(root / 'venv') in lodex_cli.__file__, lodex_cli.__file__
with patch.object(pathlib.Path, 'home', return_value=root / 'agent-fixture'):
    assert main(['skill', 'install']) == 0
    for name in SKILL_NAMES:
        assert main(['skill', 'install', name]) == 0
        assert main(['skill', 'install', name]) == 0
        assert main(['skill', 'remove', name]) == 0
store = Registry()
SQLiteSecrets(store).set('secret:upgrade-fixture', 'synthetic-upgrade-value')
store.close()
"""
        run([str(python), "-c", check, str(root)], root, env)
        run(
            [
                "uv",
                "pip",
                "install",
                "--reinstall",
                "--python",
                str(python),
                "--find-links",
                str(artifacts),
                f"{wheel}[console]",
            ],
            root,
            env,
        )
        names = json.loads(
            run([str(python), "-m", "lodex_cli.main", "secret", "list", "--json"], root, env)
        )
        assert names["result"] == ["upgrade-fixture"]
        repo = root / "repo"
        repo.mkdir()
        for args in (
            ("init", "-q"),
            ("config", "user.name", "Fixture"),
            ("config", "user.email", "fixture@example.invalid"),
        ):
            run(["git", *args], repo, env)
        (repo / ".gitignore").write_text(".env\n")
        (repo / "README.md").write_text("Installed distribution fixture\n")
        run(["git", "add", "."], repo, env)
        run(["git", "commit", "-qm", "fixture"], repo, env)
        (repo / ".lodex").mkdir()
        (repo / ".lodex/project.toml").write_text(
            'schema_version=1\n[env]\nLABEL="${LODEX_TASKENV_ID}"\n'
            '[secrets]\nTOKEN="secret:upgrade-fixture"\n[ports]\nPORT=0\n'
            + "".join(
                f"[commands.{name}]\nargv=" + json.dumps([str(python), "-c", "print('ok')"]) + "\n"
                for name in ("prepare", "verify", "cleanup")
            )
            + "[services.http]\nargv="
            + json.dumps([str(python), "-m", "http.server", "${PORT}", "--bind", "127.0.0.1"])
            + '\nready_port="PORT"\nurl="http://127.0.0.1:${PORT}"\n'
        )

        def cli(*args: str) -> object:
            return json.loads(
                run([str(python), "-m", "lodex_cli.main", *args, "--json"], root, env)
            )["result"]

        cli("project", "add", "installed-fixture", str(repo))
        cli("worktree", "attach", "installed-fixture", str(repo))
        tasks = []
        try:
            for branch in ("a", "b"):
                task = cli(
                    "worktree", "create", "installed-fixture", "--ref", "HEAD", "--branch", branch
                )
                assert isinstance(task, dict)
                tasks.append(task)
                assert Path(task["path"]).name == f"{branch}--{task['id'][:8]}"
                assert (Path(task["path"]) / ".lodex/project.toml").is_file()
                assert not (Path(task["path"]) / ".env").exists()
                for command in (
                    ("prepare",),
                    ("run", "verify"),
                    ("env", "export"),
                    ("service", "start", "http"),
                ):
                    cli(*command, "--target", task["id"])
            config = Path(tasks[0]["path"]) / ".lodex/project.toml"
            config.write_text(
                config.read_text().replace('LABEL="${LODEX_TASKENV_ID}"', 'LABEL="changed-a"')
            )
            assert cli("env", "show", "--target", tasks[0]["id"]) != cli(
                "env", "show", "--target", tasks[1]["id"]
            )
            cli("service", "stop", "http", "--target", tasks[0]["id"])
            observed = cli("service", "list", "--target", tasks[1]["id"])
            assert isinstance(observed, list) and observed[0]["state"] == "running"
            cli("worktree", "inspect", "--target", tasks[0]["id"])
        finally:
            for task in tasks:
                cli("service", "stop", "http", "--target", task["id"])
                cli("cleanup", "--target", task["id"])
                cli("worktree", "remove", "--target", task["id"], "--yes", "--force")
        cli("worktree", "forget", "--target", str(repo), "--yes")
        server = subprocess.Popen(
            [str(python), "-m", "lodex_cli.main", "console"],
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            assert server.stdout
            line = server.stdout.readline().strip().removeprefix("Lodex console: ")
            origin, token = line.split("/#token=")
            import httpx

            for _ in range(100):
                try:
                    response = httpx.get(origin)
                    if response.status_code == 200:
                        break
                except httpx.ConnectError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("Installed console did not start")
            assert "Lodex" in response.text
            import re

            for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', response.text):
                assert httpx.get(origin + asset).status_code == 200
            result = httpx.get(origin + "/api/state", headers={"Authorization": f"Bearer {token}"})
            assert result.json()["result"]["secrets"] == ["upgrade-fixture"]
        finally:
            server.terminate()
            server.wait(timeout=10)
        run(
            [
                str(python),
                str(ROOT / "scripts/verify_environments.py"),
                "--lodex",
                str(root / "venv/bin/lodex"),
            ],
            root,
            env,
        )
        print(
            "PASS: isolated Core/CLI/Server; sdist rebuilds; wheel install/reinstall; "
            "all bundled Skills; "
            "preserved data; CLI dual-environment lifecycle; packaged console assets; "
            "self-contained multi-service isolation with installed CLI"
        )


if __name__ == "__main__":
    main()
