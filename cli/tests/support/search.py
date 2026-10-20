from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from lodex_core.history.chunking import chunk_turn
from lodex_core.history.contracts import (
    EmbeddingResult,
    SessionRecord,
    TurnRecord,
)
from lodex_core.history.storage import Storage


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
