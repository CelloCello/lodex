# Lodex

Lodex is a local-first retrieval tool for coding-agent session history. Its
indexing core consumes normalized session source adapters; the currently bundled
adapter reads Codex JSONL transcripts without modifying them. Lodex generates
embeddings through a loopback-only Ollama connection and stores a hybrid
FTS5/`sqlite-vec` index in SQLite.

## Installation and usage

### Prerequisites

Install and start [Ollama](https://ollama.com/download), then download the local
embedding model. `ollama serve` keeps the API available in the foreground; use
your operating system's normal service mechanism if you want it to persist.

```bash
ollama serve
ollama pull qwen3-embedding:0.6b
```

### Install Lodex and the Codex skill

Install Lodex from a local checkout as an isolated command-line tool. This is a
non-editable installation intended for normal use; commands are available from
any project without activating the Lodex development environment.

```bash
uv tool install /absolute/path/to/lodex
lodex status
lodex skill install --dry-run
lodex skill install
```

The Codex skill is installed as a managed copy rather than a symlink, so moving
or deleting the checkout does not break it.

Codex tasks may sandbox access to the user-level database or loopback Ollama.
When a read-only `status`, `search`, or `show` command is blocked, the skill asks
for approval to retry that exact command outside the sandbox. It never extends
that approval to `index`, `rebuild`, or skill management commands.

Some Codex surfaces, including side conversations, cannot request approval. If
the database is readable and compatible but loopback Ollama is blocked by the
sandbox, the skill uses the explicit `search --lexical` mode. This queries the
existing SQLite FTS5 index without contacting Ollama and reports that semantic
recall is unavailable; it is not used for database or embedding compatibility
errors.

The default database is `~/.local/share/lodex/lodex.db`. Lodex creates the data
directory with mode `0700` and the database with mode `0600`.

### Update or remove an installation

Re-run the tool installation to update the installed CLI from the checkout:

```bash
uv tool install --force /absolute/path/to/lodex
```

When updating a schema-v1 Codex-only database, run `lodex index` once before
read-only commands. The migration tags existing sessions as `codex` and preserves
all chunks and embeddings. Before migration, `lodex status` remains read-only and
reports the legacy database's real counters and content range alongside the
compatibility error.

The CLI installation and Codex skill are updated separately. `skill install`
adds a missing skill, leaves an identical copy unchanged, and updates an older
or modified copy. Preview the operation before replacing the installed copy:

```bash
lodex skill install --dry-run
lodex skill install
```

An update replaces the complete installed skill, including local edits and
stale files. Remove only the installed skill with:

```bash
lodex skill remove --dry-run
lodex skill remove
```

Removing or reinstalling the CLI or skill does not delete the Lodex database or
the original Codex sessions.

Remove the CLI separately when it is no longer needed:

```bash
uv tool uninstall lodex
```

## Commands

```bash
# Initial backfill or incremental refresh
lodex index
lodex index --session <thread-id-or-jsonl-path>
lodex index --since 2026-08-01 --until 2026-08-07

# Sources that disappeared are marked missing; deletion is always explicit
lodex index --prune

# Hybrid vector + full-text retrieval
lodex search "why was the parser changed?"
lodex search "StorageCompatibilityError" --project current --limit 5 --json
lodex search "index transaction" --since 2026-08-01 --until 2026-08-31
lodex search "index transaction" --source codex

# Explicit FTS-only retrieval when loopback Ollama cannot be reached
lodex search "StorageCompatibilityError" --project current --lexical --json

# Expand only the matched turn and a bounded number of neighbors
lodex show <chunk-id> --context 1 --json

# Check Ollama, model identity, schema, counters, and indexed content range
lodex status --json

# Required after an incompatible model digest/dimension or chunking contract change
lodex rebuild --yes
```

Run the initial `index` until it completes. Re-running the same command is safe:
unchanged sessions and chunks do not call Ollama again, so it is also the normal
day-to-day incremental refresh command. If a run is interrupted, start it again;
successfully committed sessions are retained.

Index date filters use the timestamp in `session_meta`; date-only bounds are
inclusive and interpreted as UTC. Range indexing never marks out-of-range
sessions missing and cannot be combined with `--session` or `--prune`.

Every `--json` command writes one JSON value to stdout. Search output includes
`mode` as either `hybrid` or `lexical`. Exit codes are `0` for success, `1` for
runtime/index failures, and `2` for usage or configuration errors. Search never
silently falls back when Ollama is unavailable; lexical-only retrieval requires
the explicit `--lexical` option.

Status reports `content_since` and `content_until` from the creation timestamps
of non-missing sessions that contain indexed chunks. These bounds describe the
stored searchable content, not when its embeddings were generated, and do not
guarantee that every session between the bounds is present.

Search and show results include the agent `source`. Status includes session
counts grouped by source.

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

## Session source adapters

Agent-specific discovery and transcript parsing live under `lodex.sources`.
The generic indexer depends only on the `SessionSource` contract: an adapter
reports availability, discovers cheap session candidates, resolves an explicit
target, parses one transcript into `SessionRecord`, and handles source-specific
file relocation.

Only the `codex` adapter is bundled today. The database stores a source name on
every session, missing-source reconciliation and pruning are scoped to that
source, and retrieval results expose it. Future adapters must emit globally
unique internal session IDs; namespacing them as `<source>:<native-id>` is the
recommended convention. The Codex adapter retains its legacy IDs so existing
indexes do not need to regenerate chunk embeddings.

## Privacy and automation

Lodex reads Codex transcripts without modifying them. Transcript chunks are
sent only to the configured loopback Ollama endpoint and the derived index stays
in the local SQLite database. The installed `lodex-history` skill treats every
retrieved transcript as untrusted historical data: embedded instructions are
never commands for the current agent, and only bounded matching context should
be exposed.

Lodex does not install a scheduler, hook, daemon, or background process. Those
can be added later by invoking the existing non-interactive contracts:

```bash
# Periodic incremental refresh
lodex index --json

# Precise refresh after a Codex task completes
lodex index --session <thread-id-or-jsonl-path> --json
```

## Development

Create or synchronize the project environment, then run Lodex through the
checkout. Development does not require a user-wide tool installation.

```bash
uv sync
uv run lodex status
uv run lodex index
```

For local dogfooding, an optional editable tool installation makes `lodex`
available from other projects while reflecting Python source changes
immediately:

```bash
uv tool install --editable .
```

Re-run that command with `--force` after changing dependencies, entry points,
or other `pyproject.toml` metadata:

```bash
uv tool install --force --editable .
```

Run the local validation suite from the checkout:

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
