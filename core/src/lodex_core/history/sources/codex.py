"""Codex JSONL discovery and parsing adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from lodex_core.history.codex_parser import parse_codex_session
from lodex_core.history.contracts import SessionRecord
from lodex_core.history.dates import DateRangeError, normalize_date_filter
from lodex_core.history.sources.base import SessionCandidate, SourceError

CODEX_SOURCE = "codex"


def discover_session_files(roots: Sequence[Path]) -> tuple[Path, ...]:
    """Return deterministic active-then-archived Codex JSONL paths."""

    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(root.rglob("*.jsonl")))
    return tuple(dict.fromkeys(path.resolve() for path in files))


def session_file_header(path: Path) -> tuple[str | None, str | None]:
    """Read the first Codex session identity and timestamp from a transcript."""

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


def inspect_session_file(path: Path) -> SessionCandidate:
    """Create one cheap candidate without parsing the complete transcript."""

    identity, created_at = session_file_header(path)
    return SessionCandidate(path=path.resolve(), source_session_id=identity, created_at=created_at)


def select_canonical_sessions(
    candidates: Sequence[SessionCandidate],
) -> tuple[SessionCandidate, ...]:
    """Choose the newest Codex snapshot for each logical session identity."""

    selected: dict[str, tuple[tuple[str, int, str], SessionCandidate]] = {}
    for candidate in candidates:
        try:
            try:
                normalized_created_at = normalize_date_filter(candidate.created_at) or ""
            except DateRangeError:
                normalized_created_at = ""
            rank = (
                normalized_created_at,
                candidate.path.stat().st_mtime_ns,
                str(candidate.path),
            )
        except OSError:
            rank = ("", 0, str(candidate.path))
        key = candidate.source_session_id or f"path:{candidate.path}"
        previous = selected.get(key)
        if previous is None or rank > previous[0]:
            selected[key] = (rank, candidate)
    chosen = {candidate.path for _, candidate in selected.values()}
    return tuple(candidate for candidate in candidates if candidate.path in chosen)


class CodexSessionSource:
    """Read sessions from one Codex home without exposing its format to the core."""

    name = CODEX_SOURCE

    def __init__(self, codex_home: str | Path) -> None:
        home = Path(codex_home).expanduser().resolve()
        self.roots = (home / "sessions", home / "archived_sessions")

    def available(self) -> bool:
        return any(root.is_dir() for root in self.roots)

    def discover(self) -> tuple[SessionCandidate, ...]:
        candidates: list[SessionCandidate] = []
        for path in discover_session_files(self.roots):
            try:
                candidates.append(inspect_session_file(path))
            except OSError:
                candidates.append(SessionCandidate(path, None, None))
        return select_canonical_sessions(candidates)

    def resolve(self, target: str) -> SessionCandidate:
        candidate = Path(target).expanduser()
        if candidate.exists():
            if not candidate.is_file():
                raise SourceError(f"Session target is not a file: {candidate}")
            return inspect_session_file(candidate.resolve())

        paths = [path for path in discover_session_files(self.roots) if target in path.name]
        matches = select_canonical_sessions(tuple(inspect_session_file(path) for path in paths))
        if not matches:
            raise SourceError(f"No Codex session matches {target!r}")
        if len(matches) > 1:
            exact = [value for value in matches if value.path.stem.endswith(target)]
            if len(exact) == 1:
                return exact[0]
            raise SourceError(
                f"Codex session target {target!r} is ambiguous ({len(matches)} matches)"
            )
        return matches[0]

    def parse(self, path: Path) -> SessionRecord:
        return replace(parse_codex_session(path), source=self.name)

    def relocated(self, missing_path: Path) -> SessionCandidate | None:
        matches = [
            candidate.resolve()
            for root in self.roots
            if root.is_dir()
            for candidate in root.rglob(missing_path.name)
            if candidate.resolve() != missing_path
        ]
        candidates: list[SessionCandidate] = []
        for path in dict.fromkeys(matches):
            try:
                candidates.append(inspect_session_file(path))
            except OSError:
                continue
        canonical = select_canonical_sessions(candidates)
        if not canonical:
            return None
        if len(canonical) > 1:
            raise SourceError(
                f"Session moved from {missing_path}, but its new location is ambiguous"
            )
        return canonical[0]
