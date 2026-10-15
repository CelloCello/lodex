from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.message import SessionMessage
from mcp.types import LATEST_PROTOCOL_VERSION, JSONRPCMessage

from lodex_cli.mcp_server import create_server
from lodex_core.history import queries
from lodex_core.history.config import load_config
from lodex_core.history.embedding import OllamaUnavailableError
from lodex_core.history.storage import Storage

from .support.history import configure_cli
from .support.search import insert, session


def test_mcp_hybrid_and_errors_use_existing_retrieval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake, _ = configure_cli(monkeypatch, tmp_path)
    from lodex_cli import main as cli

    assert cli.main(["index", "--json"]) == 0
    server = create_server()

    async def check() -> None:
        # FastMCP returns (text content, structured content) for a structured tool.
        response: Any = await server.call_tool("status", {})
        assert response[1]["compatible"] is True
        response = await server.call_tool("search", {"query": "parser", "project": None})
        payload = response[1]
        assert payload["mode"] == "hybrid"
        assert payload["count"] == 1
        assert fake.query_calls == ["parser"]
        chunk_id = payload["results"][0]["chunk_id"]

        def unavailable(_: str) -> Any:
            raise OllamaUnavailableError("offline")

        monkeypatch.setattr(fake, "embed_query", unavailable)
        with pytest.raises(ToolError, match="offline"):
            await server.call_tool("search", {"query": "parser", "project": None})
        response = await server.call_tool(
            "search", {"query": "parser", "project": None, "lexical": True}
        )
        assert response[1]["mode"] == "lexical"
        response = await server.call_tool("show", {"chunk_id": chunk_id})
        assert response[1]["chunk_id"] == chunk_id

    anyio.run(check)


@pytest.mark.parametrize("tool", ["status", "search", "show"])
@pytest.mark.parametrize("late_failure", [False, True])
def test_cancelled_workers_keep_capacity_until_actual_completion(
    tool: str,
    late_failure: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lodex_cli import main as cli

    configure_cli(monkeypatch, tmp_path)
    assert cli.main(["index", "--json"]) == 0
    capsys.readouterr()
    hit = queries.search(load_config(), "parser", lexical_only=True)[0]
    arguments: dict[str, dict[str, Any]] = {
        "status": {},
        "search": {"query": "parser", "project": None},
        "show": {"chunk_id": hit.chunk_id},
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-c",
            "import sys; from support.fakes import run_gated_mcp_server; "
            "run_gated_mcp_server(sys.argv[1], hold_count=2, worker_limit=2, "
            "fail_after_release=sys.argv[2]=='1')",
            str(tmp_path),
            "1" if late_failure else "0",
        ],
        env=dict(os.environ),
        cwd=str(Path(__file__).resolve().parent),
    )

    async def wait_for(name: str) -> None:
        with anyio.fail_after(5):
            while not (tmp_path / name).exists():
                await anyio.sleep(0.01)

    async def check() -> None:
        async with stdio_client(params) as (reader, writer):

            async def send(**message: Any) -> None:
                await writer.send(
                    SessionMessage(
                        JSONRPCMessage.model_validate(
                            {
                                "jsonrpc": "2.0",
                                **message,
                            }
                        )
                    )
                )

            async def receive(request_id: int) -> dict[str, Any]:
                with anyio.fail_after(3):
                    message = await reader.receive()
                assert isinstance(message, SessionMessage)
                payload: dict[str, Any] = message.message.model_dump(
                    by_alias=True, exclude_none=True
                )
                assert payload["id"] == request_id
                return payload

            try:
                await send(
                    id=1,
                    method="initialize",
                    params={
                        "protocolVersion": LATEST_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "capacity-test", "version": "1"},
                    },
                )
                assert "result" in await receive(1)
                await send(method="notifications/initialized")

                # Fill both worker slots and cancel each request while its DB stays open.
                for request_id, marker in ((10, "started"), (11, "started-2")):
                    await send(
                        id=request_id,
                        method="tools/call",
                        params={
                            "name": tool,
                            "arguments": arguments[tool],
                        },
                    )
                    await wait_for(marker)
                    await send(method="notifications/cancelled", params={"requestId": request_id})
                    assert (await receive(request_id))["error"]["message"] == "Request cancelled"

                # Repeated retries of every tool must remain queued and cancellable;
                # cancelling them must not start another SQLite operation.
                for attempt in range(45):
                    name = ("status", "search", "show")[attempt % 3]
                    request_id = 100 + attempt
                    ping_id = 1000 + attempt
                    await send(
                        id=request_id,
                        method="tools/call",
                        params={
                            "name": name,
                            "arguments": arguments[name],
                        },
                    )
                    await send(id=ping_id, method="ping")
                    assert "result" in await receive(ping_id)
                    await send(method="notifications/cancelled", params={"requestId": request_id})
                    assert (await receive(request_id))["error"]["message"] == "Request cancelled"
                    assert not (tmp_path / "opened-3").exists()

                # A live queued request should run once the cancelled workers really finish.
                await send(
                    id=900,
                    method="tools/call",
                    params={
                        "name": "show",
                        "arguments": arguments["show"],
                    },
                )
                await send(id=901, method="ping")
                assert "result" in await receive(901)
                assert not (tmp_path / "opened-3").exists()
                assert not (tmp_path / "closed").exists()
                assert not (tmp_path / "closed-2").exists()
                (tmp_path / "release").touch()
                following = (await receive(900))["result"]
                assert not following.get("isError", False)
                assert following["structuredContent"]["chunk_id"] == hit.chunk_id
                await wait_for("closed")
                await wait_for("closed-2")
                assert (tmp_path / "opened-3").exists()
                assert not (tmp_path / "opened-4").exists()
                # Neither cancelled successes nor cancelled failures may send another reply.
                await send(id=902, method="ping")
                assert "result" in await receive(902)
                with anyio.move_on_after(0.1) as quiet:
                    await reader.receive()
                assert quiet.cancel_called
            finally:
                (tmp_path / "release").touch()

    anyio.run(check)


def test_stdio_contract_scope_validation_and_read_only_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LODEX_CONFIG", str(tmp_path / "absent.toml"))
    monkeypatch.setenv("LODEX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LODEX_EMBEDDING_DIMENSION", "3")
    monkeypatch.setenv("LODEX_OLLAMA_MODEL", "fake-model")
    # Invalid host produces a diagnostic immediately, without any network dependency.
    monkeypatch.setenv("OLLAMA_HOST", "https://remote.invalid")
    config = load_config()
    for name in ("target", "other"):
        (tmp_path / name).mkdir()
    with Storage(config.db_path, dimension=3) as storage:
        for name in ("target", "other"):
            record, project = session(
                tmp_path / f"{name}.jsonl",
                session_id=name,
                created_at="2026-09-01",
                project=f"path:{tmp_path / name}",
                texts=[("needle", "answer")],
            )
            insert(storage, replace(record, kind="direct"), project, [(1.0, 0.0, 0.0)])
    before = config.db_path.read_bytes()
    # No real Ollama access is needed for the lexical transport check.
    environment = {**os.environ, "OLLAMA_HOST": "http://127.0.0.1:1"}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "lodex_cli.main", "mcp"],
        env=environment,
        cwd=str(tmp_path / "other"),
    )

    async def check() -> None:
        with anyio.fail_after(20):
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as client:
                    initialized = await client.initialize()
                    assert initialized.serverInfo.name == "lodex"
                    tools = (await client.list_tools()).tools
                    assert {tool.name for tool in tools} == {"status", "search", "show"}
                    for tool in tools:
                        assert tool.annotations is not None
                        assert tool.annotations.readOnlyHint is True
                        assert tool.annotations.destructiveHint is False
                    search_tool = next(tool for tool in tools if tool.name == "search")
                    assert "project" in search_tool.inputSchema["required"]

                    status = await client.call_tool("status", {})
                    assert not status.isError
                    assert status.structuredContent is not None
                    assert status.structuredContent["compatible"] is False
                    assert status.structuredContent["database"]["chunks"] == 2

                    args = {
                        "query": "needle",
                        "project": str(tmp_path / "target"),
                        "kind": "direct",
                        "source": "codex",
                        "since": "2026-09-01",
                        "until": "2026-09-01",
                        "lexical": True,
                    }
                    found = await client.call_tool("search", args)
                    assert not found.isError
                    assert found.structuredContent is not None
                    payload = found.structuredContent
                    assert payload["count"] == 1
                    assert payload["results"][0]["session_id"] == "target"
                    chunk_id = payload["results"][0]["chunk_id"]
                    shown = await client.call_tool("show", {"chunk_id": chunk_id})
                    assert not shown.isError
                    assert shown.structuredContent is not None
                    assert shown.structuredContent["chunk_id"] == chunk_id

                    cross = await client.call_tool("search", {**args, "project": None})
                    assert cross.structuredContent is not None
                    assert cross.structuredContent["count"] == 2
                    for invalid in ("current", ".", "../target", "", "path:relative", "git:"):
                        assert (
                            await client.call_tool("search", {**args, "project": invalid})
                        ).isError
                    for invalid_args in (
                        {"query": "needle"},
                        {**args, "limit": 0},
                        {**args, "limit": 51},
                        {**args, "kind": "invalid"},
                        {**args, "query": ""},
                        {**args, "since": "bad-date"},
                    ):
                        assert (await client.call_tool("search", invalid_args)).isError
                    assert (
                        await client.call_tool(
                            "show",
                            {
                                "chunk_id": chunk_id,
                                "context": 11,
                            },
                        )
                    ).isError
                    assert (await client.call_tool("show", {"chunk_id": "missing"})).isError
                    assert (await client.call_tool("index", {})).isError
                    # A bad request must not prevent subsequent valid requests.
                    assert not (await client.call_tool("search", args)).isError

    anyio.run(check)
    assert config.db_path.read_bytes() == before


def test_mcp_status_does_not_create_missing_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configure_cli(monkeypatch, tmp_path)
    config = load_config()

    async def check() -> None:
        response: Any = await create_server().call_tool("status", {})
        assert response[1]["database"]["initialized"] is False

    anyio.run(check)
    assert not config.db_path.exists()


def test_status_configuration_error_matches_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from lodex_cli import main as cli

    monkeypatch.setenv("LODEX_CONFIG", str(tmp_path / "absent.toml"))
    monkeypatch.setenv("LODEX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OLLAMA_HOST", "https://remote.invalid")
    assert cli.main(["status", "--json"]) == 2
    expected = json.loads(capsys.readouterr().out)
    assert queries.inspect_status(load_config()).payload() == expected


@pytest.mark.parametrize("tool", ["status", "search", "show"])
def test_stdio_slow_tools_allow_ping_cancellation_and_other_queries(
    tool: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lodex_cli import main as cli

    configure_cli(monkeypatch, tmp_path)
    assert cli.main(["index", "--json"]) == 0
    capsys.readouterr()
    hit = queries.search(load_config(), "parser", lexical_only=True)[0]
    arguments = {
        "status": {},
        "search": {"query": "parser", "project": None},
        "show": {"chunk_id": hit.chunk_id},
    }[tool]
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-c",
            "import sys; from support.fakes import run_gated_mcp_server; "
            "run_gated_mcp_server(sys.argv[1])",
            str(tmp_path),
        ],
        env=dict(os.environ),
        cwd=str(Path(__file__).resolve().parent),
    )

    async def wait_for(name: str) -> None:
        with anyio.fail_after(5):
            while not (tmp_path / name).exists():
                await anyio.sleep(0.01)

    async def check() -> None:
        async with stdio_client(params) as (reader, writer):

            async def send(**message: Any) -> None:
                await writer.send(
                    SessionMessage(
                        JSONRPCMessage.model_validate(
                            {
                                "jsonrpc": "2.0",
                                **message,
                            }
                        )
                    )
                )

            async def receive(request_id: int) -> dict[str, Any]:
                with anyio.fail_after(3):
                    message = await reader.receive()
                assert isinstance(message, SessionMessage)
                payload: dict[str, Any] = message.message.model_dump(
                    by_alias=True, exclude_none=True
                )
                assert payload["id"] == request_id
                return payload

            try:
                await send(
                    id=1,
                    method="initialize",
                    params={
                        "protocolVersion": LATEST_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "regression", "version": "1"},
                    },
                )
                assert "result" in await receive(1)
                await send(method="notifications/initialized")
                await send(id=2, method="tools/call", params={"name": tool, "arguments": arguments})
                await wait_for("started")
                threads = json.loads((tmp_path / "started").read_text())
                assert threads["worker"] != threads["main"]

                # The slow operation is still gated, not just sleeping for a guessed interval.
                await send(id=3, method="ping")
                assert "result" in await receive(3)
                await send(
                    id=4,
                    method="tools/call",
                    params={
                        "name": "show",
                        "arguments": {"chunk_id": hit.chunk_id},
                    },
                )
                other = (await receive(4))["result"]
                assert not other.get("isError", False)
                assert other["structuredContent"]["chunk_id"] == hit.chunk_id

                await send(method="notifications/cancelled", params={"requestId": 2})
                assert (await receive(2))["error"]["message"] == "Request cancelled"
                assert not (tmp_path / "closed").exists()
                await send(
                    id=5,
                    method="tools/call",
                    params={
                        "name": "search",
                        "arguments": {"query": "parser", "project": None},
                    },
                )
                following = (await receive(5))["result"]
                assert not following.get("isError", False)
                assert following["structuredContent"]["count"] == 1

                (tmp_path / "release").touch()
                await wait_for("closed")
                # Finishing the abandoned worker must not emit a second result for id=2.
                await send(id=6, method="ping")
                assert "result" in await receive(6)
                with anyio.move_on_after(0.1) as quiet:
                    await reader.receive()
                assert quiet.cancel_called
            finally:
                (tmp_path / "release").touch()

    anyio.run(check)
