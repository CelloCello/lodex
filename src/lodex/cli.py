"""Lodex command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import asdict

from lodex import __version__
from lodex.contracts import OllamaStatus
from lodex.embedding import (
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_HOST,
    EmbeddingConfigurationError,
    OllamaEmbedder,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lodex")
    parser.add_argument("--version", action="version", version=f"lodex {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    status_parser = commands.add_parser("status", help="check local Ollama compatibility")
    status_parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _configuration_failure(host: str, model: str, message: str) -> OllamaStatus:
    return OllamaStatus(
        host=host,
        reachable=False,
        version=None,
        model=model,
        model_installed=False,
        model_digest=None,
        dimension=None,
        expected_dimension=1_024,
        compatible=False,
        error=message,
    )


def _print_status(status: OllamaStatus, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(asdict(status), ensure_ascii=False, sort_keys=True))
        return
    state = "compatible" if status.compatible else "incompatible"
    print(f"Ollama: {state}")
    print(f"  host: {status.host}")
    print(f"  version: {status.version or '-'}")
    print(f"  model: {status.model}")
    print(f"  digest: {status.model_digest or '-'}")
    dimension = status.dimension if status.dimension is not None else "-"
    print(f"  dimension: {dimension} (expected {status.expected_dimension})")
    if status.error:
        print(f"  error: {status.error}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "status":
        host = os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_HOST)
        model = os.environ.get("LODEX_OLLAMA_MODEL", DEFAULT_MODEL)
        try:
            status = OllamaEmbedder(host=host, model=model).status()
        except EmbeddingConfigurationError as exc:
            status = _configuration_failure(host, model, str(exc))
            _print_status(status, as_json=args.as_json)
            return 2
        _print_status(status, as_json=args.as_json)
        return 0 if status.compatible else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
