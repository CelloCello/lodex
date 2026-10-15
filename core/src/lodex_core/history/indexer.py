"""Incremental, resumable indexing across coding-agent session sources."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from lodex_core.history.chunking import chunk_turn
from lodex_core.history.contracts import Embedder, IndexSummary, SessionRecord
from lodex_core.history.dates import DateRangeError, normalize_date_range, timestamp_in_range
from lodex_core.history.projects import project_identity
from lodex_core.history.sources import SessionCandidate, SessionSource, SourceError
from lodex_core.history.storage import Storage


class IndexingError(RuntimeError):
    """A requested indexing operation cannot be completed."""


class SessionChangedDuringRead(IndexingError):
    """An active transcript changed repeatedly while it was being parsed."""


class IndexRuntimeError(RuntimeError):
    """The embedding runtime failed index preflight."""


def filter_session_candidates(
    candidates: tuple[SessionCandidate, ...],
    *,
    since: str | None,
    until: str | None,
) -> tuple[tuple[SessionCandidate, ...], tuple[str, ...]]:
    """Select sessions by source-provided creation timestamp without full parsing."""

    selected: list[SessionCandidate] = []
    warnings: list[str] = []
    for candidate in candidates:
        try:
            if candidate.created_at is None:
                warnings.append(f"{candidate.path}: session has no creation timestamp; skipped")
            elif timestamp_in_range(candidate.created_at, since=since, until=until):
                selected.append(candidate)
        except DateRangeError as exc:
            warnings.append(f"{candidate.path}: cannot determine session date: {exc}")
    return tuple(selected), tuple(warnings)


class Indexer:
    """Prepare embeddings outside transactions and atomically apply source deltas."""

    def __init__(
        self,
        storage: Storage,
        embedder: Embedder,
        *,
        source: SessionSource,
        progress: Callable[[int, int, Path], None] | None = None,
    ) -> None:
        self.storage = storage
        self.embedder = embedder
        self.source = source
        self.progress = progress
        self._project_cache: dict[str, str] = {}

    def index(
        self,
        *,
        target: str | None = None,
        prune: bool = False,
        since: str | None = None,
        until: str | None = None,
        force: bool = False,
    ) -> IndexSummary:
        if target is not None and prune:
            raise IndexingError("--prune cannot be combined with --session")
        if target is not None and (since is not None or until is not None):
            raise IndexingError("--since/--until cannot be combined with --session")
        if prune and (since is not None or until is not None):
            raise IndexingError("--since/--until cannot be combined with --prune")
        normalized_since, normalized_until = normalize_date_range(since, until)
        if target is None and not self.source.available():
            raise IndexingError(
                f"Configured {self.source.name} session source is unavailable; "
                "refusing to mark indexed sessions missing"
            )
        try:
            candidates = (
                (self.source.resolve(target),) if target is not None else self.source.discover()
            )
        except SourceError as exc:
            raise IndexingError(str(exc)) from exc

        date_warnings: tuple[str, ...] = ()
        if normalized_since is not None or normalized_until is not None:
            candidates, date_warnings = filter_session_candidates(
                candidates,
                since=normalized_since,
                until=normalized_until,
            )
        if candidates:
            runtime = self.embedder.status()
            if not runtime.compatible or runtime.model_digest is None or runtime.dimension is None:
                raise IndexRuntimeError(runtime.error or "Embedding runtime is incompatible")
            self.storage.validate_runtime_identity(
                model=runtime.model,
                digest=runtime.model_digest,
                dimension=runtime.dimension,
            )

        parsed_sessions = 0
        failed_sessions = 0
        unchanged_sessions = 0
        indexed_turns = 0
        embedded_chunks = 0
        warnings = list(date_warnings)
        seen_paths = {str(candidate.path) for candidate in candidates}

        for current, candidate in enumerate(candidates, start=1):
            processed_path = candidate.path
            try:
                processed_path, session, final_size, final_mtime_ns = self._load_session(
                    candidate, force=force
                )
                if processed_path != candidate.path:
                    seen_paths.discard(str(candidate.path))
                    seen_paths.add(str(processed_path))
                if session is None:
                    unchanged_sessions += 1
                    continue

                if session.source != self.source.name:
                    raise IndexingError(
                        f"Source {self.source.name!r} returned a session labeled {session.source!r}"
                    )
                parsed_sessions += 1
                chunks = tuple(chunk for turn in session.turns for chunk in chunk_turn(turn))
                existing_ids = self.storage.existing_chunk_ids(session.session_id)
                new_chunks = tuple(chunk for chunk in chunks if chunk.chunk_id not in existing_ids)
                embedding_result = (
                    self.embedder.embed_documents([chunk.text for chunk in new_chunks])
                    if new_chunks
                    else None
                )
                self.storage.replace_session(
                    session,
                    chunks,
                    new_chunks,
                    embedding_result,
                    file_size=final_size,
                    file_mtime_ns=final_mtime_ns,
                    project=self._project(session),
                )
                indexed_turns += len(session.turns)
                embedded_chunks += len(new_chunks)
                warnings.extend(
                    f"{processed_path}:{warning.line_number}:{warning.code}: {warning.message}"
                    for warning in session.warnings
                )
            except Exception as exc:
                failed_sessions += 1
                warnings.append(f"{processed_path}: {str(exc) or exc.__class__.__name__}")
            finally:
                if self.progress is not None:
                    self.progress(current, len(candidates), processed_path)

        missing_sessions = 0
        pruned_sessions = 0
        full_scan = target is None and since is None and until is None
        if full_scan and failed_sessions:
            skipped = (
                "missing-source reconciliation and prune"
                if prune
                else "missing-source reconciliation"
            )
            warnings.append(
                f"Skipped {skipped} because {failed_sessions} session(s) failed to index"
            )
        elif full_scan:
            missing_sessions = self.storage.mark_missing(
                seen_paths,
                source=self.source.name,
            )
            if prune:
                pruned_sessions = self.storage.prune_missing(source=self.source.name)
                missing_sessions = 0

        return IndexSummary(
            scanned_sessions=len(candidates),
            parsed_sessions=parsed_sessions,
            failed_sessions=failed_sessions,
            unchanged_sessions=unchanged_sessions,
            indexed_turns=indexed_turns,
            embedded_chunks=embedded_chunks,
            missing_sessions=missing_sessions,
            pruned_sessions=pruned_sessions,
            warnings=tuple(warnings),
            source=self.source.name,
        )

    def _load_session(
        self,
        candidate: SessionCandidate,
        *,
        force: bool = False,
    ) -> tuple[Path, SessionRecord | None, int, int]:
        """Read one session, following a single source-reported relocation."""

        current = candidate.path
        for attempt in range(2):
            try:
                initial_stat = current.stat()
                stored = self.storage.get_session_by_path(self.source.name, str(current))
                if (
                    not force
                    and stored is not None
                    and not stored.missing
                    and stored.provenance_indexed
                    and stored.file_size == initial_stat.st_size
                    and stored.file_mtime_ns == initial_stat.st_mtime_ns
                ):
                    return current, None, initial_stat.st_size, initial_stat.st_mtime_ns

                session, final_size, final_mtime_ns = self._parse_stable(current, initial_stat)
                return current, session, final_size, final_mtime_ns
            except FileNotFoundError:
                relocated = self.source.relocated(current)
                if attempt > 0 or relocated is None:
                    raise
                current = relocated.path

        raise AssertionError("session relocation retry exhausted")

    def _parse_stable(
        self,
        path: Path,
        initial_stat: os.stat_result,
    ) -> tuple[SessionRecord, int, int]:
        before = initial_stat
        for _ in range(2):
            session = self.source.parse(path)
            after = path.stat()
            if before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns:
                return session, after.st_size, after.st_mtime_ns
            before = after
        raise SessionChangedDuringRead(
            "Session changed repeatedly while it was being parsed; retry the index command"
        )

    def _project(self, session: SessionRecord) -> str:
        if not session.cwd:
            return ""
        if session.cwd not in self._project_cache:
            self._project_cache[session.cwd] = project_identity(session.cwd)
        return self._project_cache[session.cwd]
