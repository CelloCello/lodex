"""Read-only operations shared by the CLI and MCP server."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from lodex.config import AppConfig
from lodex.contracts import DatabaseStatus, OllamaStatus, SearchResult, ShowResult
from lodex.embedding import EmbeddingConfigurationError, OllamaEmbedder
from lodex.projects import project_identity
from lodex.retrieval import Retrieval, show_context
from lodex.storage import Storage, database_status


def create_embedder(config: AppConfig) -> OllamaEmbedder:
    return OllamaEmbedder(
        host=config.ollama_host,
        model=config.ollama_model,
        expected_dimension=config.embedding_dimension,
    )


@dataclass(frozen=True, slots=True)
class StatusReport:
    ollama: OllamaStatus
    database: DatabaseStatus
    exit_code: int

    def payload(self) -> dict[str, Any]:
        payload = asdict(self.ollama)
        payload["compatible"] = self.ollama.compatible and self.database.compatible
        payload["database"] = asdict(self.database)
        return payload


def inspect_status(config: AppConfig) -> StatusReport:
    configuration_error = False
    try:
        ollama = create_embedder(config).status()
    except EmbeddingConfigurationError as exc:
        configuration_error = True
        ollama = OllamaStatus(
            host=config.ollama_host,
            reachable=False,
            version=None,
            model=config.ollama_model,
            model_installed=False,
            model_digest=None,
            dimension=None,
            expected_dimension=config.embedding_dimension,
            compatible=False,
            error=str(exc),
        )
    database = database_status(
        config.db_path,
        dimension=config.embedding_dimension,
        provider="ollama",
        model=config.ollama_model,
        digest=ollama.model_digest,
    )
    exit_code = 2 if configuration_error else int(not (ollama.compatible and database.compatible))
    return StatusReport(ollama, database, exit_code)


def resolve_project(value: str | None) -> str | None:
    if value is None:
        return None
    if value == "current":
        return project_identity(Path.cwd())
    if value.startswith(("git:", "path:")):
        return value
    return project_identity(value)


def search(
    config: AppConfig,
    query: str,
    *,
    source: str | None = None,
    kind: str | None = None,
    project: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 10,
    lexical_only: bool = False,
) -> tuple[SearchResult, ...]:
    with Storage(config.db_path, dimension=config.embedding_dimension, read_only=True) as storage:
        return Retrieval(storage, create_embedder(config)).search(
            query,
            source=source,
            kind=kind,
            project=resolve_project(project),
            since=since,
            until=until,
            limit=limit,
            lexical_only=lexical_only,
        )


def show(config: AppConfig, chunk_id: str, *, context: int = 1) -> ShowResult:
    with Storage(config.db_path, dimension=config.embedding_dimension, read_only=True) as storage:
        return show_context(storage, chunk_id, context=context)
