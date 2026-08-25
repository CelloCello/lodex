"""Lodex command-line entry point."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Never

from lodex import __version__
from lodex.config import AppConfig, ConfigurationError, load_config
from lodex.contracts import DatabaseStatus, OllamaStatus, SearchResult, ShowResult
from lodex.dates import DateRangeError
from lodex.embedding import (
    EmbeddingConfigurationError,
    EmbeddingError,
    OllamaEmbedder,
)
from lodex.indexer import Indexer, IndexingError, IndexRuntimeError
from lodex.projects import project_identity
from lodex.retrieval import Retrieval, RetrievalError, show_context
from lodex.skill_install import install_skill, remove_skill
from lodex.sources import CodexSessionSource
from lodex.storage import (
    Storage,
    StorageCompatibilityError,
    StorageError,
    database_status,
)


class CliUsageError(ValueError):
    """An argparse usage error that the CLI can render as JSON."""


class LodexArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise CliUsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = LodexArgumentParser(prog="lodex")
    parser.add_argument("--version", action="version", version=f"lodex {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    index_parser = commands.add_parser(
        "index", help="incrementally index configured coding-agent sessions"
    )
    index_parser.add_argument("--session", help="source-native session ID or transcript path")
    index_parser.add_argument("--since", help="include sessions created on/after ISO date")
    index_parser.add_argument("--until", help="include sessions created on/before ISO date")
    index_parser.add_argument("--prune", action="store_true", help="delete missing sources")
    index_parser.add_argument("--json", action="store_true", dest="as_json")

    search_parser = commands.add_parser("search", help="hybrid-search indexed sessions")
    search_parser.add_argument("query")
    search_parser.add_argument("--source", help="coding-agent source name")
    search_parser.add_argument("--project", help="current or a project path/identity")
    search_parser.add_argument("--since")
    search_parser.add_argument("--until")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument(
        "--lexical",
        action="store_true",
        help="search with SQLite FTS only, without contacting Ollama",
    )
    search_parser.add_argument("--json", action="store_true", dest="as_json")

    show_parser = commands.add_parser("show", help="show a hit with neighboring turns")
    show_parser.add_argument("chunk_id")
    show_parser.add_argument("--context", type=int, default=1)
    show_parser.add_argument("--json", action="store_true", dest="as_json")

    status_parser = commands.add_parser("status", help="check runtime and index compatibility")
    status_parser.add_argument("--json", action="store_true", dest="as_json")

    rebuild_parser = commands.add_parser("rebuild", help="reset the local index")
    rebuild_parser.add_argument("--yes", action="store_true")
    rebuild_parser.add_argument("--json", action="store_true", dest="as_json")

    skill_parser = commands.add_parser("skill", help="manage the bundled Codex skill")
    skill_commands = skill_parser.add_subparsers(dest="skill_command", required=True)
    install_parser = skill_commands.add_parser("install", help="install or update lodex-history")
    install_parser.add_argument("--dry-run", action="store_true")
    remove_parser = skill_commands.add_parser("remove", help="remove lodex-history")
    remove_parser.add_argument("--dry-run", action="store_true")
    return parser


def _configuration_failure(
    host: str,
    model: str,
    dimension: int,
    message: str,
) -> OllamaStatus:
    return OllamaStatus(
        host=host,
        reachable=False,
        version=None,
        model=model,
        model_installed=False,
        model_digest=None,
        dimension=None,
        expected_dimension=dimension,
        compatible=False,
        error=message,
    )


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _print_status(
    ollama: OllamaStatus,
    database: DatabaseStatus,
    *,
    as_json: bool,
) -> None:
    compatible = ollama.compatible and database.compatible
    if as_json:
        payload = asdict(ollama)
        payload["compatible"] = compatible
        payload["database"] = asdict(database)
        _print_json(payload)
        return
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
    print(f"  content range: {database.content_since or '-'} to {database.content_until or '-'}")
    if ollama.error:
        print(f"  Ollama error: {ollama.error}")
    if database.error:
        print(f"  database error: {database.error}")


def _error(command: str, message: str, *, as_json: bool) -> None:
    if as_json:
        _print_json({"command": command, "error": message, "ok": False})
    else:
        print(f"lodex {command}: {message}", file=sys.stderr)


def _resolved_project(value: str | None) -> str | None:
    if value is None:
        return None
    if value == "current":
        return project_identity(Path.cwd())
    if value.startswith(("git:", "path:")):
        return value
    return project_identity(value)


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
        print(f"   {preview}")
        print(f"   {result.source_path}")


def _print_show(result: ShowResult, *, as_json: bool) -> None:
    if as_json:
        _print_json(asdict(result))
        return
    print(f"Session: {result.session_id}")
    print(f"Agent source: {result.source}")
    print(f"Source: {result.source_path}")
    for turn in result.turns:
        marker = "*" if turn.turn_id == result.matched_turn_id else " "
        print(f"{marker} Turn {turn.ordinal} [{turn.status}] {turn.turn_id}")
        if turn.user_text:
            print(f"  User: {turn.user_text}")
        if turn.assistant_text:
            print(f"  Assistant: {turn.assistant_text}")


def _embedder(config: AppConfig) -> OllamaEmbedder:
    return OllamaEmbedder(
        host=config.ollama_host,
        model=config.ollama_model,
        expected_dimension=config.embedding_dimension,
    )


def _status(config: AppConfig, *, as_json: bool) -> int:
    configuration_error = False
    try:
        ollama = _embedder(config).status()
    except EmbeddingConfigurationError as exc:
        configuration_error = True
        ollama = _configuration_failure(
            config.ollama_host,
            config.ollama_model,
            config.embedding_dimension,
            str(exc),
        )
    database = database_status(
        config.db_path,
        dimension=config.embedding_dimension,
        provider="ollama",
        model=config.ollama_model,
        digest=ollama.model_digest,
    )
    _print_status(ollama, database, as_json=as_json)
    if configuration_error:
        return 2
    return 0 if ollama.compatible and database.compatible else 1


def _as_json(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "as_json", False))


def _index_progress(current: int, total: int, path: Path) -> None:
    if current == 1 or current == total or current % 25 == 0:
        print(f"indexing [{current}/{total}] {path.name}", file=sys.stderr)


def _run_skill(args: argparse.Namespace) -> int:
    command = str(args.skill_command)
    if command == "install":
        result = install_skill(dry_run=bool(args.dry_run))
    elif command == "remove":
        result = remove_skill(dry_run=bool(args.dry_run))
    else:
        raise AssertionError(f"Unhandled skill command: {command}")

    if result.state == "would-install":
        print(f"Would install lodex-history to {result.path}")
    elif result.state == "would-update":
        print(f"Would update lodex-history at {result.path}")
    elif result.state == "would-remove":
        print(f"Would remove lodex-history from {result.path}")
    elif result.state == "unchanged":
        print(f"lodex-history is already up to date at {result.path}")
    elif result.state == "not-installed":
        print(f"lodex-history is not installed at {result.path}")
    elif result.state == "updated":
        print(f"Updated lodex-history at {result.path}")
    elif result.state == "removed":
        print(f"Removed lodex-history from {result.path}")
    else:
        print(f"Installed lodex-history to {result.path}")
    return 0


def _run(args: argparse.Namespace, config: AppConfig) -> int:
    as_json = _as_json(args)
    command = str(args.command)
    if command == "status":
        return _status(config, as_json=as_json)

    if command == "rebuild":
        if not args.yes:
            _error(command, "refusing to delete the index without --yes", as_json=as_json)
            return 2
        Storage.rebuild(config.db_path, dimension=config.embedding_dimension)
        payload = {"database": str(config.db_path), "ok": True, "rebuilt": True}
        _print_json(payload) if as_json else print(f"Rebuilt {config.db_path}")
        return 0

    if command == "index":
        with Storage(config.db_path, dimension=config.embedding_dimension) as storage:
            summary = Indexer(
                storage,
                _embedder(config),
                source=CodexSessionSource(config.codex_home),
                progress=_index_progress,
            ).index(
                target=args.session,
                prune=args.prune,
                since=args.since,
                until=args.until,
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

    if command == "search":
        with Storage(
            config.db_path,
            dimension=config.embedding_dimension,
            read_only=True,
        ) as storage:
            retrieval = Retrieval(storage, _embedder(config))
            results = retrieval.search(
                args.query,
                source=args.source,
                project=_resolved_project(args.project),
                since=args.since,
                until=args.until,
                limit=args.limit,
                lexical_only=bool(args.lexical),
            )
            _print_search(
                results,
                query=args.query,
                mode="lexical" if args.lexical else "hybrid",
                as_json=as_json,
            )
        return 0

    if command == "show":
        with Storage(
            config.db_path,
            dimension=config.embedding_dimension,
            read_only=True,
        ) as storage:
            result = show_context(storage, args.chunk_id, context=args.context)
            _print_show(result, as_json=as_json)
        return 0

    raise AssertionError(f"Unhandled command: {command}")


def main(argv: Sequence[str] | None = None) -> int:
    raw_arguments = list(argv) if argv is not None else sys.argv[1:]
    try:
        args = build_parser().parse_args(raw_arguments)
    except CliUsageError as exc:
        command = raw_arguments[0] if raw_arguments else "lodex"
        _error(command, str(exc), as_json="--json" in raw_arguments)
        return 2
    as_json = _as_json(args)
    command = str(args.command)
    try:
        if command == "skill":
            return _run_skill(args)
        config = load_config()
        return _run(args, config)
    except (
        CliUsageError,
        ConfigurationError,
        DateRangeError,
        EmbeddingConfigurationError,
        IndexingError,
        RetrievalError,
    ) as exc:
        _error(command, str(exc), as_json=as_json)
        return 2
    except (
        EmbeddingError,
        IndexRuntimeError,
        sqlite3.Error,
        StorageCompatibilityError,
        StorageError,
        OSError,
    ) as exc:
        _error(command, str(exc) or exc.__class__.__name__, as_json=as_json)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
