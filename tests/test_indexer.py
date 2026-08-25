from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

from lodex import indexer as indexer_module
from lodex.codex_parser import parse_codex_session
from lodex.contracts import EmbeddingResult, SessionRecord
from lodex.dates import DateRangeError
from lodex.indexer import Indexer, IndexingError
from lodex.storage import Storage, StorageCompatibilityError
from tests.fakes import FakeEmbedder

FIXTURES = Path(__file__).parent / "fixtures"


def make_indexer(tmp_path: Path, fake: FakeEmbedder) -> tuple[Storage, Indexer, Path, Path]:
    active = tmp_path / "sessions"
    archived = tmp_path / "archived_sessions"
    active.mkdir()
    archived.mkdir()
    storage = Storage(tmp_path / "lodex.db", dimension=fake.dimension)
    return storage, Indexer(storage, fake, roots=(active, archived)), active, archived


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


def test_move_after_discovery_is_followed_without_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeEmbedder(dimension=3)
    storage, indexer, active, archived = make_indexer(tmp_path, fake)
    source = active / "completed.jsonl"
    archived_source = archived / source.name
    shutil.copy2(FIXTURES / "completed.jsonl", source)
    original_select = indexer_module.select_canonical_session_files
    moved = False

    def select_then_move(paths: Sequence[Path]) -> tuple[Path, ...]:
        nonlocal moved
        selected = original_select(paths)
        if not moved:
            source.replace(archived_source)
            moved = True
        return selected

    monkeypatch.setattr(indexer_module, "select_canonical_session_files", select_then_move)
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
    original_parse = parse_codex_session

    def parse_then_move(path: Path) -> SessionRecord:
        session = original_parse(path)
        if path == source:
            source.replace(archived_source)
        return session

    monkeypatch.setattr(indexer_module, "parse_codex_session", parse_then_move)
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

        failed = Indexer(storage, FailingFake(3), roots=indexer.roots).index()

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

        failed = Indexer(storage, FailingFake(3), roots=indexer.roots).index(prune=True)

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

        recovered = Indexer(storage, FakeEmbedder(3), roots=indexer.roots).index(prune=True)
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
            Indexer(storage, changed_model, roots=indexer.roots).index()
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
