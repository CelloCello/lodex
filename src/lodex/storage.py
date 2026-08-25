"""SQLite, FTS5, and sqlite-vec persistence for Lodex."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import sqlite_vec  # type: ignore[import-untyped]

from lodex.chunking import (
    CHUNKING_VERSION,
    DEFAULT_MAX_CHARS,
    DEFAULT_OVERLAP_CHARS,
)
from lodex.contracts import (
    ChunkRecord,
    DatabaseStatus,
    EmbeddingResult,
    SessionRecord,
    TurnRecord,
)

SCHEMA_VERSION = 1


class StorageError(RuntimeError):
    """Base error for database operations."""


class StorageCompatibilityError(StorageError):
    """The database was built with an incompatible schema or vector contract."""


@dataclass(frozen=True, slots=True)
class StoredSession:
    session_id: str
    source_path: str
    file_size: int
    file_mtime_ns: int
    missing: bool


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _placeholders(count: int) -> str:
    return ", ".join("?" for _ in range(count))


class Storage(AbstractContextManager["Storage"]):
    """A direct SQLite boundary with atomic per-session replacement."""

    def __init__(
        self,
        path: str | Path,
        *,
        dimension: int,
        read_only: bool = False,
        _reset_existing: bool = False,
    ) -> None:
        if dimension <= 0:
            raise StorageCompatibilityError("Embedding dimension must be positive")
        if read_only and _reset_existing:
            raise StorageError("Cannot reset a read-only database")
        self.path = Path(path).expanduser().resolve()
        self.dimension = dimension
        try:
            if read_only:
                self.connection = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)
            else:
                self._prepare_path()
                self.connection = sqlite3.connect(self.path)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            if read_only:
                self.connection.execute("PRAGMA query_only = ON")
            else:
                self.connection.execute("PRAGMA journal_mode = WAL")
                self.connection.execute("PRAGMA synchronous = NORMAL")
            try:
                self.connection.enable_load_extension(True)
                sqlite_vec.load(self.connection)
            finally:
                self.connection.enable_load_extension(False)
            if _reset_existing:
                self.reset()
            elif read_only:
                self._validate_existing()
            else:
                self._migrate()
        except StorageError:
            if hasattr(self, "connection"):
                self.close()
            raise
        except sqlite3.Error as exc:
            if hasattr(self, "connection"):
                self.close()
            raise StorageError(f"Cannot open Lodex database {self.path}: {exc}") from exc
        except Exception as exc:
            if hasattr(self, "connection"):
                self.close()
            raise StorageError(
                f"Cannot initialize Lodex database {self.path}: "
                f"{str(exc) or exc.__class__.__name__}"
            ) from exc

    @classmethod
    def rebuild(cls, path: str | Path, *, dimension: int) -> None:
        """Reset an index without requiring its existing vector contract to match."""

        with cls(path, dimension=dimension, _reset_existing=True):
            pass

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _prepare_path(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        existed = self.path.exists()
        if not existed:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _migrate(self) -> None:
        version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise StorageCompatibilityError(
                f"Database schema {version} is newer than supported schema {SCHEMA_VERSION}"
            )
        if version == 0:
            self._create_schema()
        self._ensure_schema_metadata()
        stored_dimension = self.get_metadata("embedding_dimension")
        if stored_dimension is not None and int(stored_dimension) != self.dimension:
            raise StorageCompatibilityError(
                f"Database dimension {stored_dimension} does not match {self.dimension}"
            )

    def _validate_existing(self) -> None:
        version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if version == 0:
            raise StorageCompatibilityError(
                f"Database at {self.path} is not initialized; run lodex index first"
            )
        if version > SCHEMA_VERSION:
            raise StorageCompatibilityError(
                f"Database schema {version} is newer than supported schema {SCHEMA_VERSION}"
            )
        if version < SCHEMA_VERSION:
            raise StorageCompatibilityError(
                f"Database schema {version} requires migration; run lodex index first"
            )
        stored_dimension = self.get_metadata("embedding_dimension")
        if stored_dimension is None:
            raise StorageCompatibilityError("Database embedding dimension metadata is missing")
        if int(stored_dimension) != self.dimension:
            raise StorageCompatibilityError(
                f"Database dimension {stored_dimension} does not match {self.dimension}"
            )

    def _create_schema(self) -> None:
        dimension = int(self.dimension)
        try:
            self.connection.executescript(
                f"""
            BEGIN IMMEDIATE;
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                created_at TEXT,
                cwd TEXT,
                project TEXT NOT NULL,
                archived INTEGER NOT NULL CHECK (archived IN (0, 1)),
                missing INTEGER NOT NULL DEFAULT 0 CHECK (missing IN (0, 1)),
                warning_count INTEGER NOT NULL DEFAULT 0,
                file_size INTEGER NOT NULL,
                file_mtime_ns INTEGER NOT NULL,
                indexed_at TEXT NOT NULL
            );
            CREATE INDEX sessions_source_path_idx ON sessions(source_path);
            CREATE INDEX sessions_project_idx ON sessions(project);
            CREATE INDEX sessions_created_at_idx ON sessions(created_at);

            CREATE TABLE turns (
                session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                turn_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                user_text TEXT NOT NULL,
                assistant_text TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                PRIMARY KEY (session_id, turn_id)
            );
            CREATE INDEX turns_order_idx ON turns(session_id, ordinal);

            CREATE TABLE chunks (
                rowid INTEGER PRIMARY KEY,
                chunk_id TEXT NOT NULL UNIQUE,
                session_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                char_start INTEGER NOT NULL,
                char_end INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                FOREIGN KEY (session_id, turn_id)
                    REFERENCES turns(session_id, turn_id) ON DELETE CASCADE
            );
            CREATE INDEX chunks_session_idx ON chunks(session_id);
            CREATE INDEX chunks_turn_idx ON chunks(session_id, turn_id, chunk_index);

            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                text,
                chunk_id UNINDEXED,
                tokenize='unicode61 tokenchars ''_'''
            );

            CREATE VIRTUAL TABLE chunk_embeddings USING vec0(
                embedding float[{dimension}]
            );

            PRAGMA user_version = {SCHEMA_VERSION};
            COMMIT;
            """
            )
        except Exception:
            self.connection.rollback()
            raise

    def _ensure_schema_metadata(self) -> None:
        with self.connection:
            for key, value in {
                "schema_version": str(SCHEMA_VERSION),
                "embedding_dimension": str(self.dimension),
                "sqlite_vec_version": self.sqlite_vec_version,
                "chunking_version": CHUNKING_VERSION,
                "chunk_max_chars": str(DEFAULT_MAX_CHARS),
                "chunk_overlap_chars": str(DEFAULT_OVERLAP_CHARS),
            }.items():
                if self.get_metadata(key) is None:
                    self.set_metadata(key, value)

    @property
    def sqlite_vec_version(self) -> str:
        return str(self.connection.execute("SELECT vec_version()").fetchone()[0])

    def close(self) -> None:
        self.connection.close()

    def get_metadata(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row is not None else None

    def set_metadata(self, key: str, value: str) -> None:
        self.connection.execute(
            """
            INSERT INTO metadata(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def get_session_by_path(self, source_path: str) -> StoredSession | None:
        row = self.connection.execute(
            """
            SELECT session_id, source_path, file_size, file_mtime_ns, missing
            FROM sessions WHERE source_path = ?
            """,
            (source_path,),
        ).fetchone()
        return self._stored_session(row)

    def get_session(self, session_id: str) -> StoredSession | None:
        row = self.connection.execute(
            """
            SELECT session_id, source_path, file_size, file_mtime_ns, missing
            FROM sessions WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        return self._stored_session(row)

    @staticmethod
    def _stored_session(row: sqlite3.Row | None) -> StoredSession | None:
        if row is None:
            return None
        return StoredSession(
            session_id=str(row["session_id"]),
            source_path=str(row["source_path"]),
            file_size=int(row["file_size"]),
            file_mtime_ns=int(row["file_mtime_ns"]),
            missing=bool(row["missing"]),
        )

    def existing_chunk_ids(self, session_id: str) -> set[str]:
        rows = self.connection.execute(
            "SELECT chunk_id FROM chunks WHERE session_id = ?", (session_id,)
        )
        return {str(row[0]) for row in rows}

    def _validate_embedding_identity(self, result: EmbeddingResult) -> None:
        if result.dimension != self.dimension:
            raise StorageCompatibilityError(
                f"Embedding dimension {result.dimension} does not match database {self.dimension}"
            )
        expected = {
            "embedding_provider": result.provider,
            "embedding_model": result.model,
            "embedding_model_digest": result.model_digest,
            "embedding_dimension": str(result.dimension),
            "chunking_version": CHUNKING_VERSION,
            "chunk_max_chars": str(DEFAULT_MAX_CHARS),
            "chunk_overlap_chars": str(DEFAULT_OVERLAP_CHARS),
        }
        for key, value in expected.items():
            stored = self.get_metadata(key)
            if stored is not None and stored != value:
                raise StorageCompatibilityError(
                    f"Database {key}={stored!r} does not match current value {value!r}; "
                    "run lodex rebuild --yes"
                )

    def validate_query_embedding(self, result: EmbeddingResult) -> None:
        """Reject queries from a vector space different from the stored index."""

        self._validate_embedding_identity(result)
        if self.get_metadata("embedding_model_digest") is None and self.chunk_count > 0:
            raise StorageCompatibilityError(
                "Database embedding identity is incomplete; rebuild required"
            )

    def validate_runtime_identity(self, *, model: str, digest: str, dimension: int) -> None:
        """Validate an index preflight even when every source file is unchanged."""

        expected = {
            "embedding_model": model,
            "embedding_model_digest": digest,
            "embedding_dimension": str(dimension),
            "chunking_version": CHUNKING_VERSION,
            "chunk_max_chars": str(DEFAULT_MAX_CHARS),
            "chunk_overlap_chars": str(DEFAULT_OVERLAP_CHARS),
        }
        for key, value in expected.items():
            stored = self.get_metadata(key)
            if stored is None and self.chunk_count > 0:
                raise StorageCompatibilityError(
                    f"Database {key} is missing; run lodex rebuild --yes"
                )
            if stored is not None and stored != value:
                raise StorageCompatibilityError(
                    f"Database {key}={stored!r} does not match current value {value!r}; "
                    "run lodex rebuild --yes"
                )

    def replace_session(
        self,
        session: SessionRecord,
        chunks: Sequence[ChunkRecord],
        new_chunks: Sequence[ChunkRecord],
        embedding_result: EmbeddingResult | None,
        *,
        file_size: int,
        file_mtime_ns: int,
        project: str,
    ) -> None:
        """Atomically apply a fully prepared session delta."""

        if new_chunks:
            if embedding_result is None:
                raise StorageError("New chunks require embeddings")
            if len(embedding_result.embeddings) != len(new_chunks):
                raise StorageError("Embedding count does not match new chunk count")
            self._validate_embedding_identity(embedding_result)
        elif embedding_result is not None and embedding_result.embeddings:
            raise StorageError("Unexpected embeddings without new chunks")

        current_ids = self.existing_chunk_ids(session.session_id)
        desired_ids = {chunk.chunk_id for chunk in chunks}
        obsolete_ids = current_ids - desired_ids
        now = _utc_now()

        with self.connection:
            self.set_metadata("last_indexed_at", now)
            if embedding_result is not None:
                for key, value in {
                    "embedding_provider": embedding_result.provider,
                    "embedding_model": embedding_result.model,
                    "embedding_model_digest": embedding_result.model_digest,
                    "embedding_dimension": str(embedding_result.dimension),
                }.items():
                    self.set_metadata(key, value)

            self.connection.execute(
                """
                INSERT INTO sessions(
                    session_id, source_path, created_at, cwd, project, archived, missing,
                    warning_count, file_size, file_mtime_ns, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    source_path = excluded.source_path,
                    created_at = excluded.created_at,
                    cwd = excluded.cwd,
                    project = excluded.project,
                    archived = excluded.archived,
                    missing = 0,
                    warning_count = excluded.warning_count,
                    file_size = excluded.file_size,
                    file_mtime_ns = excluded.file_mtime_ns,
                    indexed_at = excluded.indexed_at
                """,
                (
                    session.session_id,
                    session.source_path,
                    session.created_at,
                    session.cwd,
                    project,
                    int(session.archived),
                    len(session.warnings),
                    file_size,
                    file_mtime_ns,
                    now,
                ),
            )

            self._delete_chunk_ids(obsolete_ids)
            for turn in session.turns:
                self.connection.execute(
                    """
                    INSERT INTO turns(
                        session_id, turn_id, ordinal, status, started_at, completed_at,
                        user_text, assistant_text, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id, turn_id) DO UPDATE SET
                        ordinal = excluded.ordinal,
                        status = excluded.status,
                        started_at = excluded.started_at,
                        completed_at = excluded.completed_at,
                        user_text = excluded.user_text,
                        assistant_text = excluded.assistant_text,
                        content_hash = excluded.content_hash
                    """,
                    (
                        turn.session_id,
                        turn.turn_id,
                        turn.ordinal,
                        turn.status,
                        turn.started_at,
                        turn.completed_at,
                        turn.user_text,
                        turn.assistant_text,
                        turn.content_hash,
                    ),
                )

            turn_ids = {turn.turn_id for turn in session.turns}
            if turn_ids:
                self.connection.execute(
                    f"DELETE FROM turns WHERE session_id = ? AND turn_id NOT IN "
                    f"({_placeholders(len(turn_ids))})",
                    (session.session_id, *sorted(turn_ids)),
                )
            else:
                self.connection.execute(
                    "DELETE FROM turns WHERE session_id = ?", (session.session_id,)
                )

            vectors = embedding_result.embeddings if embedding_result is not None else ()
            for chunk, vector in zip(new_chunks, vectors, strict=True):
                cursor = self.connection.execute(
                    """
                    INSERT INTO chunks(
                        chunk_id, session_id, turn_id, chunk_index, text,
                        char_start, char_end, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.chunk_id,
                        chunk.session_id,
                        chunk.turn_id,
                        chunk.chunk_index,
                        chunk.text,
                        chunk.char_start,
                        chunk.char_end,
                        chunk.content_hash,
                    ),
                )
                if cursor.lastrowid is None:
                    raise StorageError("SQLite did not return a chunk row ID")
                rowid = cursor.lastrowid
                self.connection.execute(
                    "INSERT INTO chunks_fts(rowid, text, chunk_id) VALUES (?, ?, ?)",
                    (rowid, chunk.text, chunk.chunk_id),
                )
                self.connection.execute(
                    "INSERT INTO chunk_embeddings(rowid, embedding) VALUES (?, ?)",
                    (rowid, sqlite_vec.serialize_float32(vector)),
                )
        self.connection.execute("PRAGMA wal_checkpoint(PASSIVE)")

    def _delete_chunk_ids(self, chunk_ids: Iterable[str]) -> None:
        values = tuple(chunk_ids)
        if not values:
            return
        rowids = [
            int(row[0])
            for row in self.connection.execute(
                f"SELECT rowid FROM chunks WHERE chunk_id IN ({_placeholders(len(values))})",
                values,
            )
        ]
        if rowids:
            placeholders = _placeholders(len(rowids))
            self.connection.execute(
                f"DELETE FROM chunk_embeddings WHERE rowid IN ({placeholders})", rowids
            )
            self.connection.execute(
                f"DELETE FROM chunks_fts WHERE rowid IN ({placeholders})", rowids
            )
        self.connection.execute(
            f"DELETE FROM chunks WHERE chunk_id IN ({_placeholders(len(values))})", values
        )

    def mark_missing(self, seen_paths: set[str]) -> int:
        rows = self.connection.execute("SELECT session_id, source_path FROM sessions").fetchall()
        missing_ids = [
            str(row["session_id"]) for row in rows if row["source_path"] not in seen_paths
        ]
        with self.connection:
            self.connection.execute("UPDATE sessions SET missing = 0")
            if missing_ids:
                self.connection.execute(
                    f"UPDATE sessions SET missing = 1 WHERE session_id IN "
                    f"({_placeholders(len(missing_ids))})",
                    missing_ids,
                )
        return len(missing_ids)

    def prune_missing(self) -> int:
        session_ids = [
            str(row[0])
            for row in self.connection.execute("SELECT session_id FROM sessions WHERE missing = 1")
        ]
        with self.connection:
            for session_id in session_ids:
                chunk_ids = [
                    str(row[0])
                    for row in self.connection.execute(
                        "SELECT chunk_id FROM chunks WHERE session_id = ?", (session_id,)
                    )
                ]
                self._delete_chunk_ids(chunk_ids)
                self.connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        return len(session_ids)

    @property
    def chunk_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    def _filter_sql(
        self,
        *,
        project: str | None,
        since: str | None,
        until: str | None,
        prefix: str = "s",
    ) -> tuple[str, list[object]]:
        clauses: list[str] = []
        values: list[object] = []
        if project:
            clauses.append(f"{prefix}.project = ?")
            values.append(project)
        if since:
            clauses.append(f"unixepoch({prefix}.created_at) >= unixepoch(?)")
            values.append(since)
        if until:
            clauses.append(f"unixepoch({prefix}.created_at) <= unixepoch(?)")
            values.append(until)
        return (" AND " + " AND ".join(clauses) if clauses else "", values)

    def vector_candidates(
        self,
        vector: Sequence[float],
        *,
        limit: int,
        project: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        filters, values = self._filter_sql(project=project, since=since, until=until)
        serialized_vector = sqlite_vec.serialize_float32(vector)

        def query(pool: int) -> list[dict[str, Any]]:
            return [
                dict(row)
                for row in self.connection.execute(
                    f"""
                    WITH nearest AS (
                        SELECT rowid, distance
                        FROM chunk_embeddings
                        WHERE embedding MATCH ? AND k = ?
                        ORDER BY distance
                    )
                    SELECT c.*, s.source_path, s.cwd, s.project, s.created_at,
                           nearest.distance
                    FROM nearest
                    JOIN chunks c ON c.rowid = nearest.rowid
                    JOIN sessions s ON s.session_id = c.session_id
                    WHERE s.missing = 0 {filters}
                    ORDER BY nearest.distance
                    LIMIT ?
                    """,
                    (serialized_vector, pool, *values, limit),
                )
            ]

        pool = max(limit * 10, 100)
        if not filters:
            return query(pool)

        eligible_count = int(
            self.connection.execute(
                f"""
                SELECT COUNT(*)
                FROM chunks c
                JOIN sessions s ON s.session_id = c.session_id
                WHERE s.missing = 0 {filters}
                """,
                values,
            ).fetchone()[0]
        )
        if eligible_count == 0:
            return []

        total_vectors = int(
            self.connection.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
        )
        target_count = min(limit, eligible_count)
        pool = min(pool, total_vectors)
        while True:
            candidates = query(pool)
            if len(candidates) >= target_count or pool >= total_vectors:
                return candidates
            pool = min(pool * 4, total_vectors)

    def lexical_candidates(
        self,
        fts_query: str,
        *,
        limit: int,
        project: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        filters, values = self._filter_sql(project=project, since=since, until=until)
        return [
            dict(row)
            for row in self.connection.execute(
                f"""
                SELECT c.*, s.source_path, s.cwd, s.project, s.created_at,
                       bm25(chunks_fts) AS lexical_score
                FROM chunks_fts
                JOIN chunks c ON c.rowid = chunks_fts.rowid
                JOIN sessions s ON s.session_id = c.session_id
                WHERE chunks_fts MATCH ? AND s.missing = 0 {filters}
                ORDER BY lexical_score
                LIMIT ?
                """,
                (fts_query, *values, limit),
            )
        ]

    def show_context(self, chunk_id: str, *, context: int) -> tuple[sqlite3.Row, list[TurnRecord]]:
        row = self.connection.execute(
            """
            SELECT c.*, t.ordinal, s.source_path, s.cwd, s.project
            FROM chunks c
            JOIN turns t ON t.session_id = c.session_id AND t.turn_id = c.turn_id
            JOIN sessions s ON s.session_id = c.session_id
            WHERE c.chunk_id = ?
            """,
            (chunk_id,),
        ).fetchone()
        if row is None:
            raise StorageError(f"Unknown chunk ID: {chunk_id}")
        turn_rows = self.connection.execute(
            """
            SELECT * FROM turns
            WHERE session_id = ? AND ordinal BETWEEN ? AND ?
            ORDER BY ordinal
            """,
            (
                row["session_id"],
                max(0, int(row["ordinal"]) - context),
                int(row["ordinal"]) + context,
            ),
        )
        turns = [self._turn_from_row(value) for value in turn_rows]
        return row, turns

    @staticmethod
    def _turn_from_row(row: sqlite3.Row) -> TurnRecord:
        return TurnRecord(
            session_id=str(row["session_id"]),
            turn_id=str(row["turn_id"]),
            ordinal=int(row["ordinal"]),
            status=str(row["status"]),  # type: ignore[arg-type]
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            user_text=str(row["user_text"]),
            assistant_text=str(row["assistant_text"]),
            content_hash=str(row["content_hash"]),
        )

    def status(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        digest: str | None = None,
    ) -> DatabaseStatus:
        metadata = {
            str(row["key"]): str(row["value"])
            for row in self.connection.execute("SELECT key, value FROM metadata")
        }
        counts = {
            table: int(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("sessions", "turns", "chunks")
        }
        missing = int(
            self.connection.execute("SELECT COUNT(*) FROM sessions WHERE missing = 1").fetchone()[0]
        )
        warnings = int(
            self.connection.execute(
                "SELECT COALESCE(SUM(warning_count), 0) FROM sessions"
            ).fetchone()[0]
        )
        compatible = int(metadata.get("embedding_dimension", "0")) == self.dimension
        for key, expected in (
            ("embedding_provider", provider),
            ("embedding_model", model),
            ("embedding_model_digest", digest),
        ):
            stored = metadata.get(key)
            if expected is not None and stored is not None and stored != expected:
                compatible = False
        return DatabaseStatus(
            path=str(self.path),
            initialized=True,
            schema_version=int(metadata.get("schema_version", SCHEMA_VERSION)),
            sqlite_vec_version=metadata.get("sqlite_vec_version"),
            provider=metadata.get("embedding_provider"),
            model=metadata.get("embedding_model"),
            model_digest=metadata.get("embedding_model_digest"),
            dimension=int(metadata["embedding_dimension"]),
            compatible=compatible,
            sessions=counts["sessions"],
            turns=counts["turns"],
            chunks=counts["chunks"],
            missing_sessions=missing,
            warnings=warnings,
            last_indexed_at=metadata.get("last_indexed_at"),
        )

    def reset(self) -> None:
        """Drop all Lodex index data and recreate the current schema."""

        self.connection.executescript(
            """
            DROP TABLE IF EXISTS chunk_embeddings;
            DROP TABLE IF EXISTS chunks_fts;
            DROP TABLE IF EXISTS chunks;
            DROP TABLE IF EXISTS turns;
            DROP TABLE IF EXISTS sessions;
            DROP TABLE IF EXISTS metadata;
            PRAGMA user_version = 0;
            """
        )
        self._create_schema()
        self._ensure_schema_metadata()


def database_status(
    path: str | Path,
    *,
    dimension: int,
    provider: str | None = None,
    model: str | None = None,
    digest: str | None = None,
) -> DatabaseStatus:
    """Inspect an existing DB without creating one when it is absent."""

    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return DatabaseStatus(
            path=str(resolved),
            initialized=False,
            schema_version=None,
            sqlite_vec_version=None,
            provider=None,
            model=None,
            model_digest=None,
            dimension=None,
            compatible=True,
        )
    try:
        with Storage(resolved, dimension=dimension, read_only=True) as storage:
            return storage.status(provider=provider, model=model, digest=digest)
    except Exception as exc:
        return DatabaseStatus(
            path=str(resolved),
            initialized=True,
            schema_version=None,
            sqlite_vec_version=None,
            provider=None,
            model=None,
            model_digest=None,
            dimension=None,
            compatible=False,
            error=str(exc) or exc.__class__.__name__,
        )
