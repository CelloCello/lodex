from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from lodex.contracts import EmbeddingResult, SessionRecord
from lodex.dates import DateRangeError
from lodex.indexer import Indexer, IndexingError
from lodex.sources import CodexSessionSource, SessionCandidate
from lodex.storage import Storage, StorageCompatibilityError
from tests.fakes import FakeEmbedder, downgrade_schema

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("version", [1, 2])
def test_origin_migration_backfills_unchanged_files_without_reembedding(
    tmp_path: Path, version: int
) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, _ = make_indexer(tmp_path, fake)
    shutil.copy2(FIXTURES / "approval-audit.jsonl", active / "audit.jsonl")
    try:
        indexer.index()
        original_ids = storage.existing_chunk_ids("session-approval")
        original_vectors = [
            tuple(row)
            for row in storage.connection.execute(
                "SELECT rowid, embedding FROM chunk_embeddings ORDER BY rowid"
            )
        ]
        downgrade_schema(storage.connection, version)
    finally:
        storage.close()
    with Storage(tmp_path / "lodex.db", dimension=3) as migrated:
        stats = migrated.status().session_kind_stats
        assert stats is not None
        assert stats.counts["unknown"] == stats.pending_sessions == 1
        indexer = Indexer(migrated, fake, source=CodexSessionSource(tmp_path))
        result = indexer.index()
        assert (result.parsed_sessions, result.embedded_chunks) == (1, 0)
        assert len(fake.document_calls) == 1
        assert migrated.existing_chunk_ids("session-approval") == original_ids
        assert [
            tuple(row)
            for row in migrated.connection.execute(
                "SELECT rowid, embedding FROM chunk_embeddings ORDER BY rowid"
            )
        ] == original_vectors
        stats = migrated.status().session_kind_stats
        assert stats is not None
        assert stats.counts["audit"] == 1
        assert stats.pending_sessions == 0
        assert indexer.index().unchanged_sessions == 1
        row, _ = migrated.show_context(next(iter(original_ids)), context=0)
        assert row["kind"] == "audit"
        assert '"guardian"' in row["provenance_json"]


def make_indexer(tmp_path: Path, fake: FakeEmbedder) -> tuple[Storage, Indexer, Path, Path]:
    active = tmp_path / "sessions"
    archived = tmp_path / "archived_sessions"
    active.mkdir()
    archived.mkdir()
    storage = Storage(tmp_path / "lodex.db", dimension=fake.dimension)
    return storage, Indexer(storage, fake, source=CodexSessionSource(tmp_path)), active, archived


def test_incremental_rerun_and_changed_turn_embed_only_delta(tmp_path: Path) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, _ = make_indexer(tmp_path, fake)
    source = active / "legacy.jsonl"
    shutil.copy2(FIXTURES / "legacy-multi-turn.jsonl", source)
    try:
        first = indexer.index()
        assert first.embedded_chunks == 2
        assert len(fake.document_calls) == 1

        second = indexer.index()
        assert second.unchanged_sessions == 1
        assert second.embedded_chunks == 0
        assert len(fake.document_calls) == 1

        content = source.read_text(encoding="utf-8")
        source.write_text(content.replace("used SQLite", "used SQLite with FTS5"), encoding="utf-8")
        changed = indexer.index()
        assert changed.embedded_chunks == 1
        assert len(fake.document_calls[-1]) == 1
        assert storage.chunk_count == 2
    finally:
        storage.close()


def test_active_to_archived_move_does_not_reembed(tmp_path: Path) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, archived = make_indexer(tmp_path, fake)
    source = active / "completed.jsonl"
    shutil.copy2(FIXTURES / "completed.jsonl", source)
    try:
        indexer.index()
        archived_source = archived / source.name
        source.replace(archived_source)

        summary = indexer.index()

        assert summary.embedded_chunks == 0
        assert len(fake.document_calls) == 1
        row = storage.connection.execute(
            "SELECT source_path, archived, missing FROM sessions"
        ).fetchone()
        assert row["source_path"] == str(archived_source.resolve())
        assert (row["archived"], row["missing"]) == (1, 0)
    finally:
        storage.close()


def test_force_refresh_repairs_old_parse_and_reuses_unchanged_embeddings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, _ = make_indexer(tmp_path, fake)
    source = active / "legacy.jsonl"
    shutil.copy2(FIXTURES / "legacy-multi-turn.jsonl", source)
    parse = indexer.source.parse

    def old_parse(path: Path) -> SessionRecord:
        session = parse(path)
        return replace(session, turns=tuple(replace(t, user_text="") for t in session.turns))

    try:
        with monkeypatch.context() as patch:
            patch.setattr(indexer.source, "parse", old_parse)
            indexer.index()
        assert indexer.index().unchanged_sessions == 1
        refreshed = indexer.index(force=True)
        assert refreshed.parsed_sessions == 1
        assert refreshed.embedded_chunks == 2
        assert len(fake.document_calls) == 2
        assert all("User:" in text for text in fake.document_calls[-1])
        assert storage.chunk_count == 2
        assert indexer.index(force=True).embedded_chunks == 0
        assert len(fake.document_calls) == 2
        users = storage.connection.execute(
            "SELECT user_text FROM turns ORDER BY ordinal"
        ).fetchall()
        assert [row[0] for row in users] == [
            "Explain the first implementation",
            "What changed later?",
        ]
    finally:
        storage.close()


def test_move_after_discovery_is_followed_without_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, archived = make_indexer(tmp_path, fake)
    source = active / "completed.jsonl"
    archived_source = archived / source.name
    shutil.copy2(FIXTURES / "completed.jsonl", source)
    original_discover = indexer.source.discover
    moved = False

    def discover_then_move() -> tuple[SessionCandidate, ...]:
        nonlocal moved
        selected = original_discover()
        if not moved:
            source.replace(archived_source)
            moved = True
        return selected

    monkeypatch.setattr(indexer.source, "discover", discover_then_move)
    try:
        summary = indexer.index()
        row = storage.connection.execute(
            "SELECT source_path, archived, missing FROM sessions"
        ).fetchone()

        assert summary.failed_sessions == 0
        assert summary.embedded_chunks == 1
        assert row["source_path"] == str(archived_source.resolve())
        assert (row["archived"], row["missing"]) == (1, 0)
    finally:
        storage.close()


def test_move_during_parse_is_followed_without_duplicate_embedding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, archived = make_indexer(tmp_path, fake)
    source = active / "completed.jsonl"
    archived_source = archived / source.name
    shutil.copy2(FIXTURES / "completed.jsonl", source)
    original_parse = indexer.source.parse

    def parse_then_move(path: Path) -> SessionRecord:
        session = original_parse(path)
        if path == source:
            source.replace(archived_source)
        return session

    monkeypatch.setattr(indexer.source, "parse", parse_then_move)
    try:
        summary = indexer.index()
        row = storage.connection.execute(
            "SELECT source_path, archived, missing FROM sessions"
        ).fetchone()

        assert summary.failed_sessions == 0
        assert summary.embedded_chunks == 1
        assert len(fake.document_calls) == 1
        assert row["source_path"] == str(archived_source.resolve())
        assert (row["archived"], row["missing"]) == (1, 0)
    finally:
        storage.close()


def test_duplicate_session_snapshots_use_latest_source_and_rerun_unchanged(
    tmp_path: Path,
) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, _ = make_indexer(tmp_path, fake)
    original = (FIXTURES / "completed.jsonl").read_text(encoding="utf-8")
    older = active / "older.jsonl"
    newer = active / "newer.jsonl"
    older.write_text(original, encoding="utf-8")
    newer.write_text(
        original.replace("2026-08-20T01:00:00Z", "2026-08-21T01:00:00Z").replace(
            "It normalizes safe transcript turns.",
            "The latest snapshot adds FTS.",
        ),
        encoding="utf-8",
    )
    try:
        first = indexer.index()
        second = indexer.index()
        row = storage.connection.execute(
            "SELECT source_path FROM sessions WHERE session_id = 'session-completed'"
        ).fetchone()
        text = storage.connection.execute("SELECT text FROM chunks").fetchone()[0]

        assert first.scanned_sessions == 1
        assert row["source_path"] == str(newer.resolve())
        assert text.endswith("The latest snapshot adds FTS.")
        assert second.unchanged_sessions == 1
        assert second.embedded_chunks == 0
        assert len(fake.document_calls) == 1
    finally:
        storage.close()


def test_missing_source_is_marked_then_explicitly_pruned(tmp_path: Path) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, _ = make_indexer(tmp_path, fake)
    source = active / "completed.jsonl"
    shutil.copy2(FIXTURES / "completed.jsonl", source)
    try:
        indexer.index()
        source.unlink()

        missing = indexer.index()
        assert missing.missing_sessions == 1
        assert storage.status().missing_sessions == 1

        pruned = indexer.index(prune=True)
        assert pruned.pruned_sessions == 1
        assert storage.status().sessions == 0
        assert storage.chunk_count == 0
    finally:
        storage.close()


def test_partial_embedding_failure_preserves_previous_session(tmp_path: Path) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, _ = make_indexer(tmp_path, fake)
    source = active / "legacy.jsonl"
    shutil.copy2(FIXTURES / "legacy-multi-turn.jsonl", source)
    try:
        indexer.index()
        before = [
            row[0] for row in storage.connection.execute("SELECT text FROM chunks ORDER BY rowid")
        ]
        content = source.read_text(encoding="utf-8")
        source.write_text(
            content.replace("used SQLite", "used a broken provider"), encoding="utf-8"
        )

        class FailingFake(FakeEmbedder):
            def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
                raise RuntimeError("embedding unavailable")

        failed = Indexer(storage, FailingFake(3), source=indexer.source).index()

        assert failed.failed_sessions == 1
        assert "embedding unavailable" in failed.warnings[0]
        after = [
            row[0] for row in storage.connection.execute("SELECT text FROM chunks ORDER BY rowid")
        ]
        assert after == before
    finally:
        storage.close()


def test_failed_archived_move_does_not_mark_or_prune_previous_session(tmp_path: Path) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, archived = make_indexer(tmp_path, fake)
    source = active / "completed.jsonl"
    shutil.copy2(FIXTURES / "completed.jsonl", source)
    try:
        indexer.index()
        archived_source = archived / source.name
        source.replace(archived_source)
        content = archived_source.read_text(encoding="utf-8")
        archived_source.write_text(
            content.replace("It normalizes", "It now normalizes"),
            encoding="utf-8",
        )

        class FailingFake(FakeEmbedder):
            def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
                raise RuntimeError("embedding unavailable")

        failed = Indexer(storage, FailingFake(3), source=indexer.source).index(prune=True)

        assert failed.failed_sessions == 1
        assert failed.missing_sessions == 0
        assert failed.pruned_sessions == 0
        assert any(
            "Skipped missing-source reconciliation and prune" in warning
            for warning in failed.warnings
        )
        assert storage.status().sessions == 1
        assert storage.status().missing_sessions == 0
        assert storage.chunk_count == 1

        recovered = Indexer(storage, FakeEmbedder(3), source=indexer.source).index(prune=True)
        row = storage.connection.execute(
            "SELECT source_path, archived, missing FROM sessions"
        ).fetchone()
        assert recovered.failed_sessions == 0
        assert row["source_path"] == str(archived_source.resolve())
        assert (row["archived"], row["missing"]) == (1, 0)
    finally:
        storage.close()


def test_truncated_session_indexes_valid_records_with_warning(tmp_path: Path) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, _ = make_indexer(tmp_path, fake)
    shutil.copy2(FIXTURES / "truncated.jsonl", active / "truncated.jsonl")
    try:
        summary = indexer.index()
        assert summary.failed_sessions == 0
        assert summary.embedded_chunks == 1
        assert any("malformed_json" in warning for warning in summary.warnings)
        assert storage.status().warnings == 2
    finally:
        storage.close()


def test_unchanged_index_still_rejects_model_digest_change(tmp_path: Path) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, _ = make_indexer(tmp_path, fake)
    shutil.copy2(FIXTURES / "completed.jsonl", active / "completed.jsonl")
    try:
        indexer.index()
        changed_model = FakeEmbedder(dimension=3, digest="changed-digest")

        with pytest.raises(StorageCompatibilityError, match="rebuild"):
            Indexer(storage, changed_model, source=indexer.source).index()
    finally:
        storage.close()


def test_targeted_session_indexes_only_requested_transcript(tmp_path: Path) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, _ = make_indexer(tmp_path, fake)
    shutil.copy2(FIXTURES / "completed.jsonl", active / "completed.jsonl")
    shutil.copy2(FIXTURES / "legacy-multi-turn.jsonl", active / "legacy.jsonl")
    try:
        summary = indexer.index(target="completed")

        assert summary.scanned_sessions == 1
        assert summary.embedded_chunks == 1
        assert storage.status().sessions == 1
    finally:
        storage.close()


def test_date_range_indexes_only_sessions_created_in_inclusive_range(tmp_path: Path) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, _ = make_indexer(tmp_path, fake)
    shutil.copy2(FIXTURES / "completed.jsonl", active / "completed.jsonl")
    shutil.copy2(FIXTURES / "legacy-multi-turn.jsonl", active / "legacy.jsonl")
    try:
        summary = indexer.index(since="2026-08-20", until="2026-08-20")

        assert summary.scanned_sessions == 1
        assert summary.embedded_chunks == 1
        assert storage.get_session("session-completed") is not None
        assert storage.get_session("session-legacy-multi") is None
    finally:
        storage.close()


def test_date_range_does_not_mark_out_of_range_sources_missing(tmp_path: Path) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, _ = make_indexer(tmp_path, fake)
    completed = active / "completed.jsonl"
    legacy = active / "legacy.jsonl"
    shutil.copy2(FIXTURES / "completed.jsonl", completed)
    shutil.copy2(FIXTURES / "legacy-multi-turn.jsonl", legacy)
    try:
        indexer.index()
        legacy.unlink()

        summary = indexer.index(since="2026-08-20")

        assert summary.missing_sessions == 0
        assert storage.status().missing_sessions == 0
        assert storage.status().sessions == 2
    finally:
        storage.close()


def test_date_range_rejects_invalid_bounds_and_unsafe_combinations(tmp_path: Path) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, _ = make_indexer(tmp_path, fake)
    shutil.copy2(FIXTURES / "completed.jsonl", active / "completed.jsonl")
    try:
        with pytest.raises(DateRangeError, match="later"):
            indexer.index(since="2026-08-21", until="2026-08-20")
        with pytest.raises(IndexingError, match="--session"):
            indexer.index(target="completed", since="2026-08-20")
        with pytest.raises(IndexingError, match="--prune"):
            indexer.index(prune=True, until="2026-08-20")
    finally:
        storage.close()
