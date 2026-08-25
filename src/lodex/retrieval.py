"""Hybrid vector/FTS retrieval and bounded context expansion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lodex.contracts import Embedder, SearchResult, ShowResult
from lodex.dates import DateRangeError, normalize_date_range
from lodex.storage import Storage

DEFAULT_CANDIDATES = 30
RRF_K = 60


class RetrievalError(ValueError):
    """A search or context request is invalid."""


def fts_query(text: str) -> str:
    """Build an operator-safe OR query suitable for identifiers and prose."""

    terms: list[str] = []
    for raw in text.split():
        term = raw.strip().strip("\"'")
        if term:
            terms.append(f'"{term.replace(chr(34), chr(34) * 2)}"')
    return " OR ".join(terms)


class Retrieval:
    """Run hybrid retrieval, or an explicitly requested lexical-only search."""

    def __init__(self, storage: Storage, embedder: Embedder) -> None:
        self.storage = storage
        self.embedder = embedder

    def search(
        self,
        query: str,
        *,
        source: str | None = None,
        project: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 10,
        lexical_only: bool = False,
    ) -> tuple[SearchResult, ...]:
        if not query.strip():
            raise RetrievalError("Search query must not be empty")
        if limit <= 0:
            raise RetrievalError("Search limit must be positive")
        if self.storage.chunk_count == 0:
            return ()

        try:
            normalized_since, normalized_until = normalize_date_range(since, until)
        except DateRangeError as exc:
            raise RetrievalError(str(exc)) from exc

        vector_rows: Sequence[Mapping[str, Any]] = ()
        if not lexical_only:
            embedding = self.embedder.embed_query(query)
            self.storage.validate_query_embedding(embedding)
            if len(embedding.embeddings) != 1:
                raise RetrievalError("Query embedder did not return exactly one vector")

            vector_rows = self.storage.vector_candidates(
                embedding.embeddings[0],
                limit=DEFAULT_CANDIDATES,
                source=source,
                project=project,
                since=normalized_since,
                until=normalized_until,
            )
        lexical = fts_query(query)
        lexical_rows = (
            self.storage.lexical_candidates(
                lexical,
                limit=DEFAULT_CANDIDATES,
                source=source,
                project=project,
                since=normalized_since,
                until=normalized_until,
            )
            if lexical
            else []
        )
        return self._merge(vector_rows, lexical_rows, limit)

    @staticmethod
    def _merge(
        vector_rows: Sequence[Mapping[str, Any]],
        lexical_rows: Sequence[Mapping[str, Any]],
        limit: int,
    ) -> tuple[SearchResult, ...]:
        rows: dict[str, Mapping[str, Any]] = {}
        scores: dict[str, float] = {}
        vector_ranks: dict[str, int] = {}
        lexical_ranks: dict[str, int] = {}
        for rank, row in enumerate(vector_rows, start=1):
            chunk_id = str(row["chunk_id"])
            rows[chunk_id] = row
            vector_ranks[chunk_id] = rank
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        for rank, row in enumerate(lexical_rows, start=1):
            chunk_id = str(row["chunk_id"])
            rows[chunk_id] = row
            lexical_ranks[chunk_id] = rank
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)

        ordered = sorted(
            scores,
            key=lambda chunk_id: (
                -scores[chunk_id],
                vector_ranks.get(chunk_id, DEFAULT_CANDIDATES + 1),
                lexical_ranks.get(chunk_id, DEFAULT_CANDIDATES + 1),
                chunk_id,
            ),
        )[:limit]
        return tuple(
            SearchResult(
                chunk_id=chunk_id,
                session_id=str(rows[chunk_id]["session_id"]),
                turn_id=str(rows[chunk_id]["turn_id"]),
                chunk_index=int(rows[chunk_id]["chunk_index"]),
                text=str(rows[chunk_id]["text"]),
                score=scores[chunk_id],
                vector_rank=vector_ranks.get(chunk_id),
                lexical_rank=lexical_ranks.get(chunk_id),
                source_path=str(rows[chunk_id]["source_path"]),
                source=str(rows[chunk_id]["source"]),
                cwd=rows[chunk_id]["cwd"],
                project=str(rows[chunk_id]["project"]),
                created_at=rows[chunk_id]["created_at"],
            )
            for chunk_id in ordered
        )

    def show(self, chunk_id: str, *, context: int = 1) -> ShowResult:
        return show_context(self.storage, chunk_id, context=context)


def show_context(storage: Storage, chunk_id: str, *, context: int = 1) -> ShowResult:
    """Expand one hit without requiring the embedding runtime."""

    if context < 0:
        raise RetrievalError("Context turn count must be non-negative")
    row, turns = storage.show_context(chunk_id, context=context)
    return ShowResult(
        chunk_id=str(row["chunk_id"]),
        session_id=str(row["session_id"]),
        source_path=str(row["source_path"]),
        source=str(row["source"]),
        cwd=row["cwd"],
        project=str(row["project"]),
        matched_turn_id=str(row["turn_id"]),
        turns=tuple(turns),
    )
