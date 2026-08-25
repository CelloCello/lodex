from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from lodex.chunking import chunk_turn
from lodex.contracts import EmbeddingResult, SessionRecord, TurnRecord
from lodex.storage import Storage, StorageCompatibilityError, StorageError, database_status


def make_session(
    source: Path,
    *,
    answer: str = "Stored answer",
    session_id: str = "session-storage",
    turn_id: str = "turn-storage",
    created_at: str = "2026-08-20T10:00:00+00:00",
) -> SessionRecord:
    turn = TurnRecord(
        session_id=session_id,
        turn_id=turn_id,
        ordinal=0,
        status="completed",
        started_at="2026-08-20T10:00:00+00:00",
        completed_at="2026-08-20T10:01:00+00:00",
        user_text="Where is StorageCompatibilityError used?",
        assistant_text=answer,
        content_hash=f"turn-{answer}",
    )
    return SessionRecord(
        session_id=session_id,
        source="codex",
        source_path=str(source),
        created_at=created_at,
        cwd=str(source.parent),
        archived=False,
        turns=(turn,),
    )


def embedding(count: int, *, digest: str = "sha256:test") -> EmbeddingResult:
    return EmbeddingResult(
        embeddings=tuple((1.0, 0.0, 0.0) for _ in range(count)),
        provider="fake",
        model="fake-model",
        model_digest=digest,
        dimension=3,
    )


def test_atomic_session_replace_populates_relational_fts_and_vec(tmp_path: Path) -> None:
    source = tmp_path / "session.jsonl"
    source.write_text("fixture", encoding="utf-8")
    session = make_session(source)
    chunks = tuple(chunk for turn in session.turns for chunk in chunk_turn(turn))

    with Storage(tmp_path / "lodex.db", dimension=3) as storage:
        storage.replace_session(
            session,
            chunks,
            chunks,
            embedding(len(chunks)),
            file_size=7,
            file_mtime_ns=1,
            project="path:/project",
        )

        status = storage.status(provider="fake", model="fake-model", digest="sha256:test")
        assert (status.sessions, status.turns, status.chunks) == (1, 1, 1)
        assert status.sources == {"codex": 1}
        assert status.compatible is True
        assert status.content_since == session.created_at
        assert status.content_until == session.created_at
        assert storage.lexical_candidates('"StorageCompatibilityError"', limit=5)
        assert (
            storage.vector_candidates((1.0, 0.0, 0.0), limit=5)[0]["chunk_id"] == chunks[0].chunk_id
        )
        row, turns = storage.show_context(chunks[0].chunk_id, context=1)
        assert row["turn_id"] == "turn-storage"
        assert turns == list(session.turns)


def test_status_content_range_uses_searchable_non_missing_sessions(tmp_path: Path) -> None:
    early_source = tmp_path / "early.jsonl"
    late_source = tmp_path / "late.jsonl"
    empty_source = tmp_path / "empty.jsonl"
    for source in (early_source, late_source, empty_source):
        source.write_text("fixture", encoding="utf-8")

    early = make_session(
        early_source,
        answer="Early answer",
        session_id="session-early",
        turn_id="turn-early",
        created_at="2026-08-19T20:00:00-04:00",
    )
    late = make_session(
        late_source,
        answer="Late answer",
        session_id="session-late",
        turn_id="turn-late",
        created_at="2026-08-21T01:00:00Z",
    )
    empty = make_session(
        empty_source,
        answer="",
        session_id="session-empty",
        turn_id="turn-empty",
        created_at="2026-08-01T00:00:00Z",
    )

    with Storage(tmp_path / "lodex.db", dimension=3) as storage:
        for session in (early, late):
            chunks = tuple(chunk for turn in session.turns for chunk in chunk_turn(turn))
            storage.replace_session(
                session,
                chunks,
                chunks,
                embedding(len(chunks)),
                file_size=7,
                file_mtime_ns=1,
                project="path:/project",
            )
        storage.replace_session(
            empty,
            (),
            (),
            None,
            file_size=7,
            file_mtime_ns=1,
            project="path:/project",
        )

        status = storage.status()
        assert status.content_since == early.created_at
        assert status.content_until == late.created_at

        storage.mark_missing({str(late_source), str(empty_source)}, source="codex")
        status = storage.status()
        assert status.content_since == late.created_at
        assert status.content_until == late.created_at


def test_changed_turn_replaces_only_obsolete_chunk(tmp_path: Path) -> None:
    source = tmp_path / "session.jsonl"
    source.write_text("fixture", encoding="utf-8")
    first = make_session(source)
    first_chunks = tuple(chunk_turn(first.turns[0]))
    changed = make_session(source, answer="Changed answer")
    changed_chunks = tuple(chunk_turn(changed.turns[0]))

    with Storage(tmp_path / "lodex.db", dimension=3) as storage:
        storage.replace_session(
            first,
            first_chunks,
            first_chunks,
            embedding(1),
            file_size=7,
            file_mtime_ns=1,
            project="path:/project",
        )
        storage.replace_session(
            changed,
            changed_chunks,
            changed_chunks,
            embedding(1),
            file_size=8,
            file_mtime_ns=2,
            project="path:/project",
        )

        assert storage.chunk_count == 1
        assert (
            storage.connection.execute("SELECT text FROM chunks")
            .fetchone()[0]
            .endswith("Changed answer")
        )
        assert storage.connection.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] == 1
        assert (
            storage.connection.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0] == 1
        )


def test_embedding_compatibility_requires_explicit_rebuild(tmp_path: Path) -> None:
    source = tmp_path / "session.jsonl"
    source.write_text("fixture", encoding="utf-8")
    session = make_session(source)
    chunks = tuple(chunk_turn(session.turns[0]))

    with Storage(tmp_path / "lodex.db", dimension=3) as storage:
        storage.replace_session(
            session,
            chunks,
            chunks,
            embedding(1),
            file_size=7,
            file_mtime_ns=1,
            project="path:/project",
        )
        with pytest.raises(StorageCompatibilityError, match="rebuild"):
            storage.validate_query_embedding(embedding(1, digest="sha256:changed"))

        storage.reset()
        status = storage.status()
        assert status.chunks == 0
        assert status.model_digest is None
        assert status.content_since is None
        assert status.content_until is None


def test_read_only_storage_queries_existing_index_without_mutating_it(tmp_path: Path) -> None:
    database = tmp_path / "lodex.db"
    source = tmp_path / "session.jsonl"
    source.write_text("fixture", encoding="utf-8")
    session = make_session(source)
    chunks = tuple(chunk_turn(session.turns[0]))
    with Storage(database, dimension=3) as storage:
        storage.replace_session(
            session,
            chunks,
            chunks,
            embedding(1),
            file_size=7,
            file_mtime_ns=1,
            project="path:/project",
        )

    modified_at = database.stat().st_mtime_ns
    with Storage(database, dimension=3, read_only=True) as storage:
        assert storage.status().chunks == 1
        assert storage.lexical_candidates('"StorageCompatibilityError"', limit=5)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            storage.connection.execute("DELETE FROM sessions")
    assert database.stat().st_mtime_ns == modified_at


def test_read_only_storage_does_not_create_a_missing_database(tmp_path: Path) -> None:
    database = tmp_path / "missing" / "lodex.db"

    with pytest.raises(StorageError, match="Cannot open Lodex database"):
        Storage(database, dimension=3, read_only=True)

    assert not database.exists()
    assert not database.parent.exists()


def test_v1_database_migrates_existing_sessions_to_codex_source(tmp_path: Path) -> None:
    database = tmp_path / "lodex.db"
    source = tmp_path / "session.jsonl"
    source.write_text("fixture", encoding="utf-8")
    session = make_session(source)
    chunks = tuple(chunk_turn(session.turns[0]))
    with Storage(database, dimension=3) as storage:
        storage.replace_session(
            session,
            chunks,
            chunks,
            embedding(1),
            file_size=7,
            file_mtime_ns=1,
            project="path:/project",
        )
        storage.connection.execute("DROP INDEX sessions_source_idx")
        storage.connection.execute("ALTER TABLE sessions DROP COLUMN source")
        storage.connection.execute("PRAGMA user_version = 1")
        storage.set_metadata("schema_version", "1")
        storage.connection.commit()

    modified_at = database.stat().st_mtime_ns
    legacy_status = database_status(
        database,
        dimension=3,
        provider="fake",
        model="fake-model",
        digest="sha256:test",
    )
    assert legacy_status.schema_version == 1
    assert legacy_status.compatible is False
    assert legacy_status.error == "Database schema 1 requires migration; run lodex index first"
    assert (legacy_status.sessions, legacy_status.turns, legacy_status.chunks) == (1, 1, 1)
    assert legacy_status.sources == {"codex": 1}
    assert legacy_status.content_since == session.created_at
    assert legacy_status.content_until == session.created_at
    assert legacy_status.dimension == 3
    assert legacy_status.provider == "fake"
    assert legacy_status.model == "fake-model"
    assert legacy_status.model_digest == "sha256:test"
    assert database.stat().st_mtime_ns == modified_at

    with Storage(database, dimension=3) as migrated:
        stored = migrated.get_session(session.session_id)
        assert stored is not None
        assert stored.source == "codex"
        assert migrated.status().schema_version == 2
        assert migrated.chunk_count == 1


def test_source_ownership_and_missing_reconciliation_are_isolated(tmp_path: Path) -> None:
    codex_source = tmp_path / "codex.jsonl"
    other_source = tmp_path / "other.log"
    codex_source.write_text("fixture", encoding="utf-8")
    other_source.write_text("fixture", encoding="utf-8")
    codex = make_session(codex_source)
    other = replace(
        make_session(
            other_source,
            answer="Other answer",
            session_id="other-agent:session-storage",
            turn_id="other-agent:turn-storage",
        ),
        source="other-agent",
    )

    with Storage(tmp_path / "lodex.db", dimension=3) as storage:
        for session in (codex, other):
            chunks = tuple(chunk_turn(session.turns[0]))
            storage.replace_session(
                session,
                chunks,
                chunks,
                embedding(1),
                file_size=7,
                file_mtime_ns=1,
                project="path:/project",
            )

        collision = replace(codex, source="other-agent")
        with pytest.raises(StorageError, match="namespace IDs"):
            storage.replace_session(
                collision,
                (),
                (),
                None,
                file_size=7,
                file_mtime_ns=1,
                project="path:/project",
            )

        assert storage.mark_missing(set(), source="codex") == 1
        rows = storage.connection.execute(
            "SELECT source, missing FROM sessions ORDER BY source"
        ).fetchall()
        assert [(row["source"], row["missing"]) for row in rows] == [
            ("codex", 1),
            ("other-agent", 0),
        ]

        assert storage.prune_missing(source="codex") == 1
        assert storage.status().sessions == 1
        assert storage.get_session(other.session_id) is not None
