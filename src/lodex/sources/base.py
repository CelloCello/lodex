"""Source contracts that keep agent-specific ingestion out of the indexer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lodex.contracts import SessionRecord


class SourceError(RuntimeError):
    """A configured coding-agent source cannot discover or resolve a session."""


@dataclass(frozen=True, slots=True)
class SessionCandidate:
    """Cheap source metadata used before a transcript requires full parsing."""

    path: Path
    source_session_id: str | None
    created_at: str | None


class SessionSource(Protocol):
    """Agent-specific discovery and parsing behind one normalized boundary.

    ``SessionRecord.session_id`` values returned by an adapter must be globally
    unique. The legacy Codex adapter preserves its existing IDs; future adapters
    should namespace their IDs with the source name.
    """

    name: str

    def available(self) -> bool:
        """Return whether at least one configured source root is readable."""

    def discover(self) -> tuple[SessionCandidate, ...]:
        """Return canonical sessions in deterministic order."""

    def resolve(self, target: str) -> SessionCandidate:
        """Resolve a source-native session ID or transcript path."""

    def parse(self, path: Path) -> SessionRecord:
        """Normalize one transcript into the shared session contract."""

    def relocated(self, missing_path: Path) -> SessionCandidate | None:
        """Resolve a transcript moved by the source lifecycle, if possible."""
