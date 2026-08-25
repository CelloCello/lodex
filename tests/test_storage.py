from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lodex.chunking import chunk_turn
from lodex.contracts import EmbeddingResult, SessionRecord, TurnRecord
from lodex.storage import Storage, StorageCompatibilityError, StorageError


def make_session(source: Path, *, answer: str = "Stored answer") -> SessionRecord:
    turn = TurnRecord(
        session_id="session-storage",
        turn_id="turn-storage",
        ordinal=0,
        status="completed",
        started_at="2026-08-20T10:00:00+00:00",
        completed_at="2026-08-20T10:01:00+00:00",
        user_text="Where is StorageCompatibilityError used?",
        assistant_text=answer,
        content_hash=f"turn-{answer}",
    )
    return SessionRecord(
        session_id="session-storage",
        source_path=str(source),
        created_at="2026-08-20T10:00:00+00:00",
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
        assert status.compatible is True
        assert storage.lexical_candidates('"StorageCompatibilityError"', limit=5)
        assert (
            storage.vector_candidates((1.0, 0.0, 0.0), limit=5)[0]["chunk_id"] == chunks[0].chunk_id
        )
        row, turns = storage.show_context(chunks[0].chunk_id, context=1)
        assert row["turn_id"] == "turn-storage"
        assert turns == list(session.turns)


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
        assert storage.status().chunks == 0
        assert storage.status().model_digest is None


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
