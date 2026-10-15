"""Typed history commands; history dependencies load only when a command runs."""

from __future__ import annotations

import json
import sys
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from lodex_cli.support import CommandError, Json, Yes
from lodex_core.history.contracts import SessionKind

if TYPE_CHECKING:
    from lodex_core.history.config import AppConfig
    from lodex_core.history.contracts import DatabaseStatus, OllamaStatus, SearchResult, ShowResult


@contextmanager
def history_errors() -> Generator[None, None, None]:
    from lodex_core.history.config import ConfigurationError
    from lodex_core.history.dates import DateRangeError
    from lodex_core.history.embedding import EmbeddingConfigurationError, EmbeddingError
    from lodex_core.history.indexer import IndexingError, IndexRuntimeError
    from lodex_core.history.retrieval import RetrievalError
    from lodex_core.history.storage import StorageCompatibilityError, StorageError

    try:
        yield
    except (
        ConfigurationError,
        DateRangeError,
        EmbeddingConfigurationError,
        IndexingError,
        RetrievalError,
    ) as exc:
        raise CommandError(str(exc), 2) from exc
    except (EmbeddingError, IndexRuntimeError, StorageCompatibilityError, StorageError) as exc:
        raise CommandError(str(exc) or exc.__class__.__name__, 1) from exc


@contextmanager
def configuration() -> Generator[AppConfig, None, None]:
    from lodex_core.history.config import load_config

    with history_errors():
        yield load_config()


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _print_status(
    ollama: OllamaStatus,
    database: DatabaseStatus,
) -> None:
    compatible = ollama.compatible and database.compatible
    state = "compatible" if compatible else "incompatible"
    print(f"Lodex: {state}")
    print(f"  Ollama host: {ollama.host}")
    print(f"  Ollama version: {ollama.version or '-'}")
    print(f"  model: {ollama.model}")
    print(f"  digest: {ollama.model_digest or '-'}")
    dimension = ollama.dimension if ollama.dimension is not None else "-"
    print(f"  dimension: {dimension} (expected {ollama.expected_dimension})")
    print(f"  database: {database.path}")
    print(f"  indexed: {database.sessions} sessions, {database.chunks} chunks")
    source_counts = ", ".join(
        f"{source}={count}" for source, count in sorted(database.sources.items())
    )
    print(f"  agent sources: {source_counts or '-'}")
    kinds = database.session_kind_stats
    if kinds is None:
        print("  session kinds (non-missing sessions): unavailable")
    else:
        counts = ", ".join(f"{kind}={count}" for kind, count in kinds.counts.items())
        print(f"  session kinds (non-missing sessions, {kinds.total_sessions} total): {counts}")
        print(f"  origins pending backfill: {kinds.pending_sessions}")
    print(f"  content range: {database.content_since or '-'} to {database.content_until or '-'}")
    stats = database.user_text_stats
    if stats is None:
        print("  user text (non-missing sessions): unavailable")
    else:
        ratio = f"{stats.nonempty_ratio:.2%}" if stats.nonempty_ratio is not None else "N/A"
        print(
            f"  user text (non-missing sessions): {stats.nonempty_turns}/{stats.total_turns} "
            f"turns non-empty ({ratio}), {stats.empty_turns} empty"
        )
    print("  Compatibility checks runtime/index format; text presence does not prove completeness.")
    if ollama.error:
        print(f"  Ollama error: {ollama.error}")
    if database.error:
        print(f"  database error: {database.error}")


def _print_search(
    results: Sequence[SearchResult],
    *,
    query: str,
    mode: str,
    as_json: bool,
) -> None:
    if as_json:
        _print_json(
            {
                "count": len(results),
                "mode": mode,
                "query": query,
                "results": [asdict(result) for result in results],
            }
        )
        return
    if not results:
        print("No results.")
        return
    for index, result in enumerate(results, start=1):
        preview = result.text.replace("\n", " ")[:240]
        print(f"{index}. {result.chunk_id}  score={result.score:.6f}")
        print(f"   agent={result.source} kind={result.kind}")
        print(f"   {preview}")
        print(f"   {result.source_path}")


def _print_show(result: ShowResult, *, as_json: bool) -> None:
    if as_json:
        _print_json(asdict(result))
        return
    print(f"Session: {result.session_id}")
    print(f"Agent source: {result.source}")
    print(f"Session kind: {result.kind}")
    print(f"Provenance: {json.dumps(dict(result.provenance), ensure_ascii=False, sort_keys=True)}")
    print(f"Source: {result.source_path}")
    for turn in result.turns:
        marker = "*" if turn.turn_id == result.matched_turn_id else " "
        print(f"{marker} Turn {turn.ordinal} [{turn.status}] {turn.turn_id}")
        if turn.user_text:
            print(f"  User: {turn.user_text}")
        if turn.assistant_text:
            print(f"  Assistant: {turn.assistant_text}")


def _index_progress(current: int, total: int, path: Path) -> None:
    if current == 1 or current == total or current % 25 == 0:
        print(f"indexing [{current}/{total}] {path.name}", file=sys.stderr)


def index(
    session: Annotated[str | None, typer.Option(help="Session ID or transcript path.")] = None,
    since: Annotated[str | None, typer.Option(help="Include sessions on/after ISO date.")] = None,
    until: Annotated[str | None, typer.Option(help="Include sessions on/before ISO date.")] = None,
    prune: Annotated[bool, typer.Option("--prune", help="Delete missing sources.")] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Reparse unchanged files after parser updates.")
    ] = False,
    as_json: Json = False,
) -> int:
    """Build or incrementally refresh the history index."""
    from lodex_core.history import queries
    from lodex_core.history.indexer import Indexer
    from lodex_core.history.sources import CodexSessionSource
    from lodex_core.history.storage import Storage

    with configuration() as config:
        with Storage(config.db_path, dimension=config.embedding_dimension) as storage:
            summary = Indexer(
                storage,
                queries.create_embedder(config),
                source=CodexSessionSource(config.codex_home),
                progress=_index_progress,
            ).index(
                target=session,
                prune=prune,
                since=since,
                until=until,
                force=force,
            )
        if as_json:
            _print_json(asdict(summary))
        else:
            print(
                f"Scanned {summary.scanned_sessions}; parsed {summary.parsed_sessions}; "
                f"embedded {summary.embedded_chunks}; failed {summary.failed_sessions}."
            )
            for warning in summary.warnings:
                print(f"warning: {warning}")
        return 1 if summary.failed_sessions else 0


def search(
    query: str,
    source: Annotated[str | None, typer.Option(help="Coding-agent source name.")] = None,
    kind: Annotated[SessionKind | None, typer.Option(help="Session origin kind.")] = None,
    project: Annotated[str | None, typer.Option(help="current or a project path/identity.")] = None,
    since: Annotated[str | None, typer.Option()] = None,
    until: Annotated[str | None, typer.Option()] = None,
    limit: Annotated[int, typer.Option()] = 10,
    lexical: Annotated[
        bool, typer.Option("--lexical", help="Search with SQLite FTS only, without Ollama.")
    ] = False,
    as_json: Json = False,
) -> int:
    """Search indexed sessions using hybrid or explicit lexical retrieval."""
    from lodex_core.history import queries

    with configuration() as config:
        results = queries.search(
            config,
            query,
            source=source,
            kind=kind,
            project=project,
            since=since,
            until=until,
            limit=limit,
            lexical_only=lexical,
        )
        _print_search(
            results, query=query, mode="lexical" if lexical else "hybrid", as_json=as_json
        )
        return 0


def show(chunk_id: str, context: Annotated[int, typer.Option()] = 1, as_json: Json = False) -> int:
    """Show a history hit with neighboring turns."""
    from lodex_core.history import queries

    with configuration() as config:
        _print_show(queries.show(config, chunk_id, context=context), as_json=as_json)
        return 0


def status(as_json: Json = False) -> int:
    """Check history runtime, model and index compatibility."""
    from lodex_core.history import queries

    with configuration() as config:
        report = queries.inspect_status(config)
        if as_json:
            _print_json(report.payload())
        else:
            _print_status(report.ollama, report.database)
        return report.exit_code


def rebuild(yes: Yes = False, as_json: Json = False) -> int:
    """Reset the derived history index; requires --yes."""
    from lodex_core.history.storage import Storage

    with configuration() as config:
        if not yes:
            raise CommandError("refusing to delete the index without --yes", 2)
        Storage.rebuild(config.db_path, dimension=config.embedding_dimension)
        payload = {"database": str(config.db_path), "ok": True, "rebuilt": True}
        _print_json(payload) if as_json else print(f"Rebuilt {config.db_path}")
        return 0


def mcp() -> int:
    """Serve read-only history status/search/show tools over MCP stdio."""
    with history_errors():
        from lodex_cli.mcp_server import create_server

        create_server().run(transport="stdio")
    return 0


def register(app: typer.Typer) -> None:
    for command in (index, search, show, status, rebuild, mcp):
        app.command()(command)
