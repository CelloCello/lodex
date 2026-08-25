"""Incremental, resumable indexing of local Codex session files."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from lodex.chunking import chunk_turn
from lodex.codex_parser import parse_codex_session
from lodex.contracts import Embedder, IndexSummary, SessionRecord
from lodex.dates import (
    DateRangeError,
    normalize_date_filter,
    normalize_date_range,
    timestamp_in_range,
)
from lodex.projects import project_identity
from lodex.storage import Storage


class IndexingError(RuntimeError):
    """A requested indexing operation cannot be completed."""


class SessionChangedDuringRead(IndexingError):
    """An active transcript changed repeatedly while it was being parsed."""


class IndexRuntimeError(RuntimeError):
    """The embedding runtime failed index preflight."""


def discover_session_files(roots: Sequence[Path]) -> tuple[Path, ...]:
    """Return deterministic active-then-archived JSONL paths."""

    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(root.rglob("*.jsonl")))
    return tuple(dict.fromkeys(path.resolve() for path in files))


def session_file_header(path: Path) -> tuple[str | None, str | None]:
    """Read the first session_meta identity and timestamp from one transcript."""

    with path.open("r", encoding="utf-8") as transcript:
        for raw_line in transcript:
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, Mapping) or record.get("type") != "session_meta":
                continue
            payload_value = record.get("payload")
            payload = payload_value if isinstance(payload_value, Mapping) else {}
            identity = payload.get("id") or payload.get("session_id")
            timestamp = payload.get("timestamp") or record.get("timestamp")
            return (
                identity.strip() if isinstance(identity, str) and identity.strip() else None,
                timestamp.strip() if isinstance(timestamp, str) and timestamp.strip() else None,
            )
    return None, None


def select_canonical_session_files(paths: Sequence[Path]) -> tuple[Path, ...]:
    """Choose the newest snapshot for each logical session identity."""

    selected: dict[str, tuple[tuple[str, int, str], Path]] = {}
    for path in paths:
        try:
            identity, created_at = session_file_header(path)
            try:
                normalized_created_at = normalize_date_filter(created_at) or ""
            except DateRangeError:
                normalized_created_at = ""
            rank = (normalized_created_at, path.stat().st_mtime_ns, str(path))
        except OSError:
            identity = None
            rank = ("", 0, str(path))
        key = identity or f"path:{path}"
        previous = selected.get(key)
        if previous is None or rank > previous[0]:
            selected[key] = (rank, path)
    chosen = {path for _, path in selected.values()}
    return tuple(path for path in paths if path in chosen)


def resolve_session_target(target: str, roots: Sequence[Path]) -> Path:
    """Resolve an explicit JSONL path or a Codex thread/session identifier."""

    candidate = Path(target).expanduser()
    if candidate.exists():
        if not candidate.is_file():
            raise IndexingError(f"Session target is not a file: {candidate}")
        return candidate.resolve()

    matches = list(
        select_canonical_session_files(
            [path for path in discover_session_files(roots) if target in path.name]
        )
    )
    if not matches:
        raise IndexingError(f"No Codex session matches {target!r}")
    if len(matches) > 1:
        exact = [path for path in matches if path.stem.endswith(target)]
        if len(exact) == 1:
            return exact[0]
        raise IndexingError(f"Session target {target!r} is ambiguous ({len(matches)} matches)")
    return matches[0]


def session_created_at(path: Path) -> str | None:
    """Read only enough JSONL records to find the canonical session timestamp."""

    return session_file_header(path)[1]


def filter_session_files(
    paths: Sequence[Path],
    *,
    since: str | None,
    until: str | None,
) -> tuple[tuple[Path, ...], tuple[str, ...]]:
    """Select sessions by canonical creation timestamp without full parsing."""

    selected: list[Path] = []
    warnings: list[str] = []
    for path in paths:
        try:
            created_at = session_created_at(path)
            if created_at is None:
                warnings.append(f"{path}: session has no creation timestamp; skipped")
            elif timestamp_in_range(created_at, since=since, until=until):
                selected.append(path)
        except (OSError, DateRangeError) as exc:
            warnings.append(f"{path}: cannot determine session date: {exc}")
    return tuple(selected), tuple(warnings)


class Indexer:
    """Prepare embeddings outside transactions and atomically apply session deltas."""

    def __init__(
        self,
        storage: Storage,
        embedder: Embedder,
        *,
        roots: Sequence[Path],
        progress: Callable[[int, int, Path], None] | None = None,
    ) -> None:
        self.storage = storage
        self.embedder = embedder
        self.roots = tuple(root.expanduser().resolve() for root in roots)
        self.progress = progress
        self._project_cache: dict[str, str] = {}

    def index(
        self,
        *,
        target: str | None = None,
        prune: bool = False,
        since: str | None = None,
        until: str | None = None,
    ) -> IndexSummary:
        if target is not None and prune:
            raise IndexingError("--prune cannot be combined with --session")
        if target is not None and (since is not None or until is not None):
            raise IndexingError("--since/--until cannot be combined with --session")
        if prune and (since is not None or until is not None):
            raise IndexingError("--since/--until cannot be combined with --prune")
        normalized_since, normalized_until = normalize_date_range(since, until)
        if target is None and not any(root.is_dir() for root in self.roots):
            raise IndexingError(
                "No configured Codex session root exists; refusing to mark indexed sessions missing"
            )
        paths = (
            (resolve_session_target(target, self.roots),)
            if target is not None
            else select_canonical_session_files(discover_session_files(self.roots))
        )
        date_warnings: tuple[str, ...] = ()
        if normalized_since is not None or normalized_until is not None:
            paths, date_warnings = filter_session_files(
                paths,
                since=normalized_since,
                until=normalized_until,
            )
        if paths:
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
        seen_paths = {str(path) for path in paths}

        for current, path in enumerate(paths, start=1):
            processed_path = path
            try:
                processed_path, session, final_size, final_mtime_ns = self._load_session(path)
                if processed_path != path:
                    seen_paths.discard(str(path))
                    seen_paths.add(str(processed_path))
                if session is None:
                    unchanged_sessions += 1
                    continue

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
                    self.progress(current, len(paths), processed_path)

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
            missing_sessions = self.storage.mark_missing(seen_paths)
            if prune:
                pruned_sessions = self.storage.prune_missing()
                missing_sessions = 0

        return IndexSummary(
            scanned_sessions=len(paths),
            parsed_sessions=parsed_sessions,
            failed_sessions=failed_sessions,
            unchanged_sessions=unchanged_sessions,
            indexed_turns=indexed_turns,
            embedded_chunks=embedded_chunks,
            missing_sessions=missing_sessions,
            pruned_sessions=pruned_sessions,
            warnings=tuple(warnings),
        )

    def _load_session(
        self,
        path: Path,
    ) -> tuple[Path, SessionRecord | None, int, int]:
        """Read one session, following a single active-to-archived move."""

        current = path
        for attempt in range(2):
            try:
                initial_stat = current.stat()
                stored = self.storage.get_session_by_path(str(current))
                if (
                    stored is not None
                    and not stored.missing
                    and stored.file_size == initial_stat.st_size
                    and stored.file_mtime_ns == initial_stat.st_mtime_ns
                ):
                    return current, None, initial_stat.st_size, initial_stat.st_mtime_ns

                session, final_size, final_mtime_ns = self._parse_stable(current, initial_stat)
                return current, session, final_size, final_mtime_ns
            except FileNotFoundError:
                relocated = self._relocated_path(current)
                if attempt > 0 or relocated is None:
                    raise
                current = relocated

        raise AssertionError("session relocation retry exhausted")

    def _relocated_path(self, missing_path: Path) -> Path | None:
        matches = [
            candidate.resolve()
            for root in self.roots
            if root.is_dir()
            for candidate in root.rglob(missing_path.name)
            if candidate.resolve() != missing_path
        ]
        canonical = select_canonical_session_files(tuple(dict.fromkeys(matches)))
        if not canonical:
            return None
        if len(canonical) > 1:
            raise IndexingError(
                f"Session moved from {missing_path}, but its new location is ambiguous"
            )
        return canonical[0]

    @staticmethod
    def _parse_stable(
        path: Path,
        initial_stat: os.stat_result,
    ) -> tuple[SessionRecord, int, int]:
        before = initial_stat
        for _ in range(2):
            session = parse_codex_session(path)
            after = path.stat()
            if before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns:
                return session, after.st_size, after.st_mtime_ns
            before = after
        raise SessionChangedDuringRead(
            "Session changed repeatedly while being parsed; retry the index command"
        )

    def _project(self, session: SessionRecord) -> str:
        if not session.cwd:
            return ""
        if session.cwd not in self._project_cache:
            self._project_cache[session.cwd] = project_identity(session.cwd)
        return self._project_cache[session.cwd]


def index_paths(
    storage: Storage,
    embedder: Embedder,
    roots: Iterable[Path],
    *,
    target: str | None = None,
    prune: bool = False,
    since: str | None = None,
    until: str | None = None,
) -> IndexSummary:
    """Convenience entry point for CLI callers and focused tests."""

    return Indexer(storage, embedder, roots=tuple(roots)).index(
        target=target,
        prune=prune,
        since=since,
        until=until,
    )
