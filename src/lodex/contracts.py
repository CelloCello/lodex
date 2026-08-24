"""Shared domain contracts for parsing, chunking, indexing, and embedding."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

TurnStatus = Literal["completed", "aborted", "active"]
EmbeddingPurpose = Literal["document", "query"]


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
    """Normalized metadata and turns from one read-only Codex JSONL file."""

    session_id: str
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
class EmbeddingRequest:
    """Provider-independent embedding request."""

    inputs: tuple[str, ...]
    purpose: EmbeddingPurpose


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
    """Machine-readable counters shared by future indexing commands."""

    scanned_sessions: int = 0
    parsed_sessions: int = 0
    failed_sessions: int = 0
    unchanged_sessions: int = 0
    indexed_turns: int = 0
    embedded_chunks: int = 0
    warnings: tuple[str, ...] = ()


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
