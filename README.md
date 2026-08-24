# Lodex

Lodex is a local-first retrieval tool for Codex session history. It reads Codex
JSONL transcripts without modifying them, generates embeddings through a
loopback-only Ollama connection, and stores a hybrid FTS5/`sqlite-vec` index in
SQLite.

## Setup

```bash
uv sync
ollama pull qwen3-embedding:0.6b
uv run lodex status
```

The default database is `~/.local/share/lodex/lodex.db`. Lodex creates the data
directory with mode `0700` and the database with mode `0600`.

## Commands

```bash
# Initial backfill or incremental refresh
uv run lodex index
uv run lodex index --session <thread-id-or-jsonl-path>
uv run lodex index --since 2026-08-01 --until 2026-08-07

# Sources that disappeared are marked missing; deletion is always explicit
uv run lodex index --prune

# Hybrid vector + full-text retrieval
uv run lodex search "why was the parser changed?"
uv run lodex search "StorageCompatibilityError" --project current --limit 5 --json
uv run lodex search "index transaction" --since 2026-08-01 --until 2026-08-31

# Expand only the matched turn and a bounded number of neighbors
uv run lodex show <chunk-id> --context 1 --json

# Check Ollama, model identity, schema, and index counters
uv run lodex status --json

# Required after an incompatible model digest/dimension or chunking contract change
uv run lodex rebuild --yes
```

Index date filters use the timestamp in `session_meta`; date-only bounds are
inclusive and interpreted as UTC. Range indexing never marks out-of-range
sessions missing and cannot be combined with `--session` or `--prune`.

Every `--json` command writes one JSON value to stdout. Exit codes are `0` for
success, `1` for runtime/index failures, and `2` for usage or configuration
errors. Search does not silently fall back to lexical-only results when Ollama
is unavailable.

## Configuration

Lodex optionally reads `~/.config/lodex/config.toml`:

```toml
[paths]
codex_home = "~/.codex"
data_dir = "~/.local/share/lodex"
# db_path = "~/.local/share/lodex/lodex.db"

[embedding]
host = "http://127.0.0.1:11434"
model = "qwen3-embedding:0.6b"
dimension = 1024
```

`LODEX_CONFIG`, `LODEX_DATA_DIR`, `LODEX_DB_PATH`, `CODEX_HOME`, `OLLAMA_HOST`,
`LODEX_OLLAMA_MODEL`, and `LODEX_EMBEDDING_DIMENSION` override TOML values.
Lodex rejects every non-loopback `OLLAMA_HOST`, so transcript text cannot be
sent to a remote embedding endpoint by mistake.

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src tests
```

The real Ollama contract test is marked separately:

```bash
uv run pytest -m ollama tests/test_ollama_integration.py
```
