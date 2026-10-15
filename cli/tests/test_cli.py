from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from lodex_cli import main as cli
from lodex_core.history import queries
from lodex_core.history.embedding import OllamaUnavailableError
from lodex_core.history.storage import Storage, StorageCompatibilityError

from .support import FIXTURES
from .support.fakes import downgrade_schema
from .support.history import configure_cli


@pytest.mark.parametrize(
    ("host", "error_fragment"),
    [
        ("https://ollama.example.com", "Remote Ollama hosts are disabled"),
        ("http://127.0.0.1:bad", "port must be an integer"),
    ],
)
def test_status_json_reports_configuration_errors_without_traceback(
    host: str,
    error_fragment: str,
) -> None:
    environment: Mapping[str, str] = {**os.environ, "OLLAMA_HOST": host}

    result = subprocess.run(
        [sys.executable, "-m", "lodex_cli.main", "status", "--json"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 2
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["compatible"] is False
    assert error_fragment in payload["error"]


def test_json_commands_are_parseable_and_incremental(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake, _ = configure_cli(monkeypatch, tmp_path)

    assert cli.main(["index", "--since", "2026-08-20", "--until", "2026-08-20", "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["embedded_chunks"] == 1
    assert first["source"] == "codex"

    assert cli.main(["index", "--json"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["embedded_chunks"] == 0
    assert len(fake.document_calls) == 1

    assert cli.main(["index", "--force", "--json"]) == 0
    forced = json.loads(capsys.readouterr().out)
    assert forced["parsed_sessions"] == 1
    assert forced["embedded_chunks"] == 0

    assert cli.main(["search", "parser", "--json"]) == 0
    search = json.loads(capsys.readouterr().out)
    assert search["count"] == 1
    assert search["results"][0]["source"] == "codex"
    chunk_id = search["results"][0]["chunk_id"]

    assert cli.main(["show", chunk_id, "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["chunk_id"] == chunk_id
    assert shown["source"] == "codex"
    assert len(shown["turns"]) == 1

    assert cli.main(["status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["compatible"] is True
    assert status["database"]["chunks"] == 1
    assert status["database"]["sources"] == {"codex": 1}
    assert status["database"]["content_since"] == "2026-08-20T01:00:00Z"
    assert status["database"]["content_until"] == "2026-08-20T01:00:00Z"

    assert cli.main(["status"]) == 0
    human_status = capsys.readouterr().out
    assert "agent sources: codex=1" in human_status
    assert "content range: 2026-08-20T01:00:00Z to 2026-08-20T01:00:00Z" in human_status


def test_status_json_reports_real_counts_for_legacy_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_cli(monkeypatch, tmp_path)
    database = tmp_path / "data" / "lodex.db"
    assert cli.main(["index", "--json"]) == 0
    capsys.readouterr()
    with Storage(database, dimension=3) as storage:
        downgrade_schema(storage.connection, 1)

    assert cli.main(["status", "--json"]) == 1
    status = json.loads(capsys.readouterr().out)
    assert status["compatible"] is False
    assert status["database"]["schema_version"] == 1
    assert status["database"]["sessions"] == 1
    assert status["database"]["turns"] == 1
    assert status["database"]["chunks"] == 1
    assert status["database"]["sources"] == {"codex": 1}
    assert status["database"]["user_text_stats"]["nonempty_ratio"] == 1.0
    assert status["database"]["content_since"] == "2026-08-20T01:00:00Z"
    assert "requires migration" in status["database"]["error"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1


def test_origin_fixtures_scoped_index_status_and_search(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake, sessions = configure_cli(monkeypatch, tmp_path)
    (sessions / "completed.jsonl").unlink()
    for name in ("approval-audit.jsonl", "automation.jsonl", "unknown-origin.jsonl"):
        shutil.copy2(FIXTURES / name, sessions / name)
    assert cli.main(["index", "--since", "2026-09-01", "--until", "2026-09-03", "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert (summary["parsed_sessions"], summary["indexed_turns"]) == (3, 5)
    assert cli.main(["status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["compatible"] is True
    assert status["database"]["user_text_stats"] == {
        "scope": "non_missing_sessions",
        "total_turns": 5,
        "nonempty_turns": 4,
        "empty_turns": 1,
        "nonempty_ratio": 0.8,
    }
    assert status["database"]["session_kind_stats"] == {
        "scope": "non_missing_sessions",
        "total_sessions": 3,
        "pending_sessions": 0,
        "counts": {"direct": 0, "audit": 1, "automation": 1, "subagent": 0, "unknown": 1},
    }
    assert cli.main(["status"]) == 0
    output = capsys.readouterr().out
    assert "4/5 turns non-empty (80.00%), 1 empty" in output
    assert "text presence does not prove completeness" in output
    for query, session_id in (
        ("ApprovalAuditFixture", "session-approval"),
        ("AutomationFixture", "session-automation"),
        ("UnknownOriginFixture", "session-unknown-origin"),
    ):
        assert cli.main(["search", query, "--lexical", "--json"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["count"] > 0
        assert {hit["session_id"] for hit in result["results"]} == {session_id}
    calls = len(fake.document_calls)
    assert (
        cli.main(
            ["index", "--force", "--session", str(sessions / "approval-audit.jsonl"), "--json"]
        )
        == 0
    )
    refresh = json.loads(capsys.readouterr().out)
    assert refresh["parsed_sessions"] == 1
    assert refresh["embedded_chunks"] == 0
    assert len(fake.document_calls) == calls
    assert cli.main(["search", "ApprovalAuditFixture", "--kind", "audit", "--json"]) == 0
    hits = json.loads(capsys.readouterr().out)["results"]
    assert len(hits) == 1
    assert hits[0]["kind"] == "audit"
    assert hits[0]["provenance"]["source"] == {"subagent": {"other": "guardian"}}
    assert cli.main(["show", hits[0]["chunk_id"], "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["kind"] == "audit"
    assert shown["provenance"] == hits[0]["provenance"]
    assert (
        cli.main(["search", "ApprovalAuditFixture", "--kind", "direct", "--lexical", "--json"]) == 0
    )
    assert json.loads(capsys.readouterr().out)["count"] == 0
    assert cli.main(["search", "anything", "--kind", "invalid", "--json"]) == 2
    capsys.readouterr()


def test_status_user_text_unavailable_and_empty_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_cli(monkeypatch, tmp_path)
    assert cli.main(["status"]) == 0
    assert "user text (non-missing sessions): unavailable" in capsys.readouterr().out
    with Storage(tmp_path / "data" / "lodex.db", dimension=3):
        pass
    assert cli.main(["status"]) == 0
    assert "0/0 turns non-empty (N/A), 0 empty" in capsys.readouterr().out


def test_json_usage_error_and_rebuild_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_cli(monkeypatch, tmp_path)
    database = tmp_path / "data" / "lodex.db"

    assert cli.main(["index", "--json"]) == 0
    capsys.readouterr()
    with pytest.raises(StorageCompatibilityError, match="dimension"):
        Storage(database, dimension=4)

    assert cli.main(["search", "query", "--limit", "0", "--json"]) == 2
    assert "positive" in json.loads(capsys.readouterr().out)["error"]

    assert cli.main(["search", "query", "--limit", "invalid", "--json"]) == 2
    message = json.loads(capsys.readouterr().out)["error"]
    assert "--limit" in message and "integer" in message

    assert cli.main(["index", "--since", "2026-08-21", "--until", "2026-08-20", "--json"]) == 2
    assert "later" in json.loads(capsys.readouterr().out)["error"]

    assert cli.main(["rebuild", "--json"]) == 2
    assert "--yes" in json.loads(capsys.readouterr().out)["error"]

    monkeypatch.setenv("LODEX_EMBEDDING_DIMENSION", "4")
    assert cli.main(["rebuild", "--yes", "--json"]) == 0
    rebuilt = json.loads(capsys.readouterr().out)
    assert rebuilt["rebuilt"] is True
    with Storage(database, dimension=4) as storage:
        assert storage.status().dimension == 4
        assert storage.status().chunks == 0


def test_ollama_unavailable_does_not_fall_back_to_lexical_search(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake, _ = configure_cli(monkeypatch, tmp_path)
    assert cli.main(["index", "--json"]) == 0
    capsys.readouterr()

    def unavailable(_: str) -> object:
        raise OllamaUnavailableError("runtime stopped")

    monkeypatch.setattr(fake, "embed_query", unavailable)
    assert cli.main(["search", "parser", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "runtime stopped"

    assert cli.main(["search", "parser", "--lexical", "--json"]) == 0
    lexical = json.loads(capsys.readouterr().out)
    assert lexical["mode"] == "lexical"
    assert lexical["count"] == 1
    assert lexical["results"][0]["vector_rank"] is None


def test_sqlite_error_is_rendered_as_json_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_cli(monkeypatch, tmp_path)

    def unavailable_storage(*_: object, **__: object) -> object:
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(queries, "Storage", unavailable_storage)
    assert cli.main(["show", "missing", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "unable to open database file"
