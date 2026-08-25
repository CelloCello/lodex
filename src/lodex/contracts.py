"""Shared domain contracts for parsing, chunking, indexing, and embedding."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

TurnStatus = Literal["completed", "aborted", "active"]


@dataclass(frozen=True, slots=True)
class ParseWarning:
    """A recoverable problem encountered while parsing a transcript."""

    line_number: int
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class TurnRecord:
    """A normalized user/assistant turn safe to include in retrieval."""

    session_id: str
    turn_id: str
    ordinal: int
    status: TurnStatus
    started_at: str | None
    completed_at: str | None
    user_text: str
    assistant_text: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """Normalized metadata and turns from one read-only agent session."""

    session_id: str
    source: str
    source_path: str
    created_at: str | None
    cwd: str | None
    archived: bool
    turns: tuple[TurnRecord, ...]
    warnings: tuple[ParseWarning, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    """A stable, bounded text unit derived from one normalized turn."""

    chunk_id: str
    session_id: str
    turn_id: str
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """Validated embeddings and the model identity that produced them."""

    embeddings: tuple[tuple[float, ...], ...]
    provider: str
    model: str
    model_digest: str
    dimension: int


@dataclass(frozen=True, slots=True)
class IndexSummary:
    """Machine-readable counters from one indexing pass."""

    scanned_sessions: int = 0
    parsed_sessions: int = 0
    failed_sessions: int = 0
    unchanged_sessions: int = 0
    indexed_turns: int = 0
    embedded_chunks: int = 0
    missing_sessions: int = 0
    pruned_sessions: int = 0
    warnings: tuple[str, ...] = ()
    source: str = ""


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One hybrid-retrieval hit with enough source context to inspect it."""

    chunk_id: str
    session_id: str
    turn_id: str
    chunk_index: int
    text: str
    score: float
    vector_rank: int | None
    lexical_rank: int | None
    source_path: str
    source: str
    cwd: str | None
    project: str
    created_at: str | None


@dataclass(frozen=True, slots=True)
class ShowResult:
    """A matched chunk and bounded neighboring turn context."""

    chunk_id: str
    session_id: str
    source_path: str
    source: str
    cwd: str | None
    project: str
    matched_turn_id: str
    turns: tuple[TurnRecord, ...]


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    """Schema, compatibility, and index counters for the local database."""

    path: str
    initialized: bool
    schema_version: int | None
    sqlite_vec_version: str | None
    provider: str | None
    model: str | None
    model_digest: str | None
    dimension: int | None
    compatible: bool
    sessions: int = 0
    turns: int = 0
    chunks: int = 0
    sources: Mapping[str, int] = field(default_factory=dict)
    missing_sessions: int = 0
    warnings: int = 0
    content_since: str | None = None
    content_until: str | None = None
    last_indexed_at: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class OllamaStatus:
    """Operational and compatibility status for the embedding runtime."""

    host: str
    reachable: bool
    version: str | None
    model: str
    model_installed: bool
    model_digest: str | None
    dimension: int | None
    expected_dimension: int
    compatible: bool
    error: str | None = None


class Embedder(Protocol):
    """Thin provider boundary used by production and deterministic fakes."""

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
        """Embed raw document chunks without adding a query instruction."""

    def embed_query(self, text: str) -> EmbeddingResult:
        """Embed one retrieval query using the provider's query convention."""

    def status(self) -> OllamaStatus:
        """Return runtime and model compatibility diagnostics."""
