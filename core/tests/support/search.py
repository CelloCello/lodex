from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from lodex_core.history.chunking import chunk_turn
from lodex_core.history.contracts import (
    EmbeddingResult,
    OllamaStatus,
    SessionRecord,
    TurnRecord,
)
from lodex_core.history.storage import Storage


class QueryEmbedder:
    def __init__(self, vectors: dict[str, tuple[float, float, float]]) -> None:
        self.vectors = vectors
        self.query_calls: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
        raise AssertionError("search must not embed documents")

    def embed_query(self, text: str) -> EmbeddingResult:
        self.query_calls.append(text)
        vector = self.vectors.get(text, (0.0, 0.0, 1.0))
        return result((vector,))

    def status(self) -> OllamaStatus:
        raise AssertionError("search must not call status")


def result(vectors: Sequence[Sequence[float]]) -> EmbeddingResult:
    return EmbeddingResult(
        embeddings=tuple(tuple(vector) for vector in vectors),
        provider="fake",
        model="fake-model",
        model_digest="sha256:test",
        dimension=3,
    )


def session(
    source: Path,
    *,
    session_id: str,
    created_at: str,
    project: str,
    texts: Sequence[tuple[str, str]],
) -> tuple[SessionRecord, str]:
    turns = tuple(
        TurnRecord(
            session_id=session_id,
            turn_id=f"{session_id}-turn-{ordinal}",
            ordinal=ordinal,
            status="completed",
            started_at=created_at,
            completed_at=created_at,
            user_text=user,
            assistant_text=assistant,
            content_hash=f"hash-{session_id}-{ordinal}",
        )
        for ordinal, (user, assistant) in enumerate(texts)
    )
    record = SessionRecord(
        session_id=session_id,
        source="codex",
        source_path=str(source),
        created_at=created_at,
        cwd=str(source.parent),
        archived=False,
        turns=turns,
    )
    return record, project


def insert(
    storage: Storage,
    record: SessionRecord,
    project: str,
    vectors: Sequence[Sequence[float]],
) -> tuple[str, ...]:
    chunks = tuple(chunk for turn in record.turns for chunk in chunk_turn(turn))
    storage.replace_session(
        record,
        chunks,
        chunks,
        result(vectors),
        file_size=1,
        file_mtime_ns=1,
        project=project,
    )
    return tuple(chunk.chunk_id for chunk in chunks)


def build_corpus(storage: Storage, tmp_path: Path) -> dict[str, tuple[str, ...]]:
    first, project_a = session(
        tmp_path / "a.jsonl",
        session_id="session-a",
        created_at="2026-08-10T00:00:00+00:00",
        project="path:/project-a",
        texts=(
            ("Where is StorageCompatibilityError?", "It is defined in src/lodex/storage.py."),
            ("Why use an atomic transaction?", "It prevents a partial index commit."),
            ("What happens next?", "Run the validation suite."),
        ),
    )
    second, project_b = session(
        tmp_path / "b.jsonl",
        session_id="session-b",
        created_at="2026-07-01T00:00:00+00:00",
        project="path:/project-b",
        texts=(("How is UI styled?", "Use design tokens."),),
    )
    return {
        "a": insert(
            storage,
            first,
            project_a,
            ((1.0, 0.0, 0.0), (0.9, 0.1, 0.0), (0.0, 1.0, 0.0)),
        ),
        "b": insert(storage, second, project_b, ((0.0, 0.0, 1.0),)),
    }
