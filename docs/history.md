# Session history

[Back to README](../README.md)

Lodex's history tools help you and your coding agent recover decisions, earlier
attempts and evidence from past sessions. The indexing core consumes normalized
session source adapters; the currently bundled adapter reads Codex JSONL
transcripts without modifying them. Lodex generates
embeddings through a loopback-only Ollama connection and stores a hybrid
FTS5/`sqlite-vec` index in SQLite.

Install the CLI using the [installation instructions](../README.md#installation).
The setup below applies only to history retrieval; management commands do not
require Ollama.

## Setup

Install and start [Ollama](https://ollama.com/download). If it is not already
running, run `ollama serve` in a separate terminal; it keeps the API available in
the foreground. Then download the local embedding model:

```bash
ollama pull qwen3-embedding:0.6b
```

Then check the runtime and build the initial index:

```bash
lodex status
lodex index
lodex search "why was the parser changed?" --project current
```

## Commands

All commands below begin with `lodex`. Except for `mcp`, they support `--json`.
Replace uppercase placeholders with actual values; square brackets denote
optional arguments. Use `lodex COMMAND --help` for the complete argument list.

| Command | Purpose and options |
| --- | --- |
| `index` | Incrementally index sessions. Scope with `--session ID_OR_PATH` or `--since DATE --until DATE`; `--force` reparses unchanged files; `--prune` deletes missing sources from the index. |
| `search QUERY` | Hybrid retrieval by default. Filter with `--project current` or a path/identity, `--source`, `--kind`, `--since` and `--until`. `--limit` defaults to 10; `--lexical` explicitly uses only FTS. |
| `show CHUNK_ID [--context N]` | Expand a hit with neighboring turns; context defaults to 1. |
| `status` | Check Ollama, model identity, index compatibility and stored content counters. Does not report management state. |
| `rebuild --yes` | Reset the derived index. Refuses without `--yes`; run `index` afterward to repopulate it. Original transcripts and management data are unaffected. |
| `mcp` | Run the read-only history MCP server over stdio, normally launched by an MCP client. |

```bash
# Initial backfill or incremental refresh
lodex index
lodex index --session <thread-id-or-jsonl-path>
lodex index --force
lodex index --since 2026-08-01 --until 2026-08-07

# Sources that disappeared are marked missing; deletion is always explicit
lodex index --prune

# Hybrid vector + full-text retrieval
lodex search "why was the parser changed?"
lodex search "StorageCompatibilityError" --project current --limit 5 --json
lodex search "index transaction" --since 2026-08-01 --until 2026-08-31
lodex search "index transaction" --source codex
lodex search "permission to read project files" --kind audit
lodex search "requirements" --kind direct --project current
lodex search "scheduled summary" --kind automation

# Explicit FTS-only retrieval when loopback Ollama cannot be reached
lodex search "StorageCompatibilityError" --project current --lexical --json

# Expand only the matched turn and a bounded number of neighbors
lodex show <chunk-id> --context 1 --json

# Check Ollama, model identity, schema, counters, and indexed content range
lodex status --json

# Required after an incompatible model digest/dimension or chunking contract change
lodex rebuild --yes
lodex index
```

Run the initial `index` until it completes. Re-running the same command is safe:
unchanged sessions and chunks do not call Ollama again, so it is also the normal
day-to-day incremental refresh command. If a run is interrupted, start it again;
successfully committed sessions are retained.

After a parser update, run `lodex index --force` to reparse unchanged transcripts
and replace their indexed turns. Unchanged chunks reuse their existing embeddings;
only new or changed chunks are embedded. This can also be scoped with `--session`
or date filters. A normal incremental run skips unchanged source files.

The Codex parser reads user text from both `event_msg.user_message` and
`response_item.message` input text, pairing duplicate representations within each
turn while retaining repeated requests and steering messages. Standalone injected
AGENTS.md instructions and environment context blocks are excluded.

Index date filters use the timestamp in `session_meta`; date-only bounds are
inclusive and interpreted as UTC. Range indexing never marks out-of-range
sessions missing and cannot be combined with `--session` or `--prune`.

Every history `--json` command writes one JSON value to stdout. Search output includes
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

Search supports `--kind direct|audit|automation|subagent|unknown`, independently of
`--source codex`, project, and date filters. Omitting `--kind` searches all kinds.
Both lexical and hybrid retrieval apply the kind filter before selecting the final
results. Search and show expose `kind` and `provenance` in JSON; text output labels
the kind, and show also prints the original provenance fields.

Kinds describe the indexed **session's origin**, not the author of every message
or the origin of inherited fork context. The Codex adapter preserves the original
`thread_source`, structured or string `source`, `originator`, `parent_thread_id`,
and `forked_from_id` when present. It classifies structural signals as follows:

| Signal | Kind |
| --- | --- |
| `thread_source=guardian_review` | `audit` |
| `source.subagent.other=guardian`, with absent or `subagent` thread source | `audit` |
| `thread_source=user`, without a subagent source | `direct` |
| `thread_source=automation` | `automation` |
| `thread_source=subagent`, or an explicit subagent source without thread source | `subagent` |
| Missing/unrecognized signals or a conflicting guardian source | `unknown` |

Client names such as `vscode`, `cli`, and `exec`, and words in the prompt, do not
establish a kind. Original fields are retained even when classification is unknown.
Origin metadata is not added to chunk text or embeddings.

Default ranking remains relevance-based reciprocal rank fusion (RRF), with no
origin boost or penalty. Direct tasks are not always the relevant evidence:
approval decisions and scheduled-run results may answer the query, and older
human conversations can have unknown origins. Use `--kind` when the desired
origin is known. Origin filters do not remove injected or quoted content inside
a transcript; a direct session label is not a guarantee that every chunk contains
a direct user request.

`database.session_kind_stats` reports `total_sessions`, `counts` for all five
kinds, and `pending_sessions`, scoped to `non_missing_sessions`. Archived sessions
are included. A zero pending count means origins were processed, not that every
session could be classified; old transcripts can legitimately remain unknown.
An unavailable database returns `null` for these statistics.

Status also reports `database.user_text_stats` in JSON: `total_turns`,
`nonempty_turns`, `empty_turns`, and `nonempty_ratio` (0–1), with scope
`non_missing_sessions`. These counts cover stored turns in non-missing sessions,
including archived sessions and all turn statuses. Empty and ASCII-whitespace-only
text counts as empty; the parser strips surrounding whitespace before storage.
The denominator differs from the existing `turns` counter, which includes missing
sessions. With no eligible turns, counts are zero and the ratio is `null` (N/A in
text output). If the database is absent or cannot be inspected, the whole stats
object is `null` (unavailable).

`compatible` describes runtime/index compatibility, not content completeness.
Text presence does not establish human authorship or correct turn alignment;
assistant-only turns can legitimately have empty user text. Reading these
statistics requires no reindexing or schema migration.

## Configuration

History shares Lodex's default root, `~/.lodex`, controlled by `LODEX_HOME`.
Commands optionally read `$LODEX_HOME/history/config.toml` and default to
`$LODEX_HOME/history/lodex.db` for the index. An absent configuration file uses
defaults; commands do not create a configuration file automatically.

For example, `~/.lodex/history/config.toml` can contain:

```toml
[paths]
codex_home = "~/.codex"
# Optional overrides; otherwise derived from LODEX_HOME/history.
# data_dir = "/absolute/path/to/history"
# db_path = "/absolute/path/to/history/lodex.db"

[embedding]
host = "http://127.0.0.1:11434"
model = "qwen3-embedding:0.6b"
dimension = 1024
```

Path resolution follows these rules:

- Configuration: `LODEX_CONFIG`, otherwise `$LODEX_HOME/history/config.toml`.
- Data directory: `LODEX_DATA_DIR`, then TOML `paths.data_dir`, otherwise
  `$LODEX_HOME/history`.
- Database: `LODEX_DB_PATH`, then TOML `paths.db_path`, otherwise `lodex.db`
  inside the resolved data directory. An explicit database path takes precedence
  over the data directory.

`CODEX_HOME`, `OLLAMA_HOST`, `LODEX_OLLAMA_MODEL`, and `LODEX_EMBEDDING_DIMENSION`
override their corresponding TOML values. Source transcripts remain in the agent's
own directories; changing `LODEX_HOME` changes Lodex's defaults, not `CODEX_HOME`.
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

History indexing does not install a scheduler or hook and runs only when invoked.
To automate refreshes, have your scheduler invoke the CLI. When configured, the
MCP client manages its own Lodex stdio child process:

```bash
# Periodic incremental refresh
lodex index --json

# Precise refresh after a Codex task completes
lodex index --session <thread-id-or-jsonl-path> --json
```

## Connect Codex through MCP

Lodex provides a local stdio MCP server with three read-only tools: `status`,
`search`, and `show`. It shares the CLI's configuration, database, and retrieval
implementation. Existing CLI commands and indexing workflows remain available.
There is no second index, HTTP port, or separately managed daemon.

After updating the installed Lodex CLI and skill, register the server once:

```bash
codex mcp add lodex -- /absolute/path/to/lodex mcp
codex mcp get lodex
```

Use the installed executable's absolute path (`command -v lodex`), not a shell
alias. Codex starts the process on demand. Reload/restart MCP in the client, or
restart Codex, to load a newly registered or updated server. Keep Ollama running
as before. Run `lodex index` separately when you want to refresh history.

The equivalent entry in `~/.codex/config.toml` is:

```toml
[mcp_servers.lodex]
command = "/absolute/path/to/lodex"
args = ["mcp"]
```

The skill prefers MCP in both normal tasks and side conversations. Verify that
your Codex version exposes custom MCP tools in the conversation you use:
call `status` and confirm `database.path` matches the resolved history configuration
(default `$LODEX_HOME/history/lodex.db`, with `LODEX_HOME` defaulting to `~/.lodex`),
then a project-scoped `search`, then `show` on one hit. A successful
standalone stdio test does not establish that a particular side chat loads the
tools. The configured MCP process must have access to the local database and
loopback Ollama; launching `lodex mcp` in a restricted shell inherits that shell's
restrictions and does not grant access.

MCP `search` requires an explicit `project`: an absolute project path, a stable
`git:`/absolute `path:` identity, or `null` for intentionally cross-project queries.
It rejects `current` and relative paths because the server's working directory
is not necessarily the task's project. Other filters match the CLI. `limit` is
1–50 (default 5); `show.context` is 0–10 (default 1). `lexical=true` explicitly
selects FTS-only retrieval. Search errors are MCP tool errors; `status` returns
the CLI JSON diagnostic fields, including `compatible` and component errors.
Retrieved history is untrusted evidence, not executable instructions.

The server exposes no indexing, rebuild, arbitrary SQL, shell, or configuration
tools. Status/search/show open SQLite read-only; SQLite may still create WAL
sidecar files. MCP stdout is reserved for protocol messages; diagnostics use
stderr. Configuration is read on each call, but package code stays loaded in the
running process. After a package update, ensure the previous MCP process exits
and the client starts its replacement, then verify that conversation's `status`.
Starting a separate test process does not refresh the existing connection. To disconnect, run
`codex mcp remove lodex`; this does not remove the CLI, skill, or index.

Tool operations run in worker threads, so a slow Ollama or SQLite call does not
block the MCP event loop. They share a separate query capacity of 40 workers,
leaving AnyIO's default capacity available for stdio transport.
When all slots are occupied, new queries wait; pings and cancellation
notifications remain responsive. Each operation opens and closes its SQLite
connection in the same worker. MCP acknowledges cancellation immediately, but
an already-running synchronous operation keeps its slot until it finishes or
reaches its existing I/O timeout and closes its connection. Its result is then
discarded. Cancelling a queued query removes it without starting its operation.
Graceful server shutdown also waits for active operations to finish cleanup.

## CLI sandbox fallback

When MCP is unavailable, Codex tasks may sandbox access to the user-level database or loopback Ollama.
When a read-only `status`, `search`, or `show` command is blocked, the skill asks
for approval to retry that exact command outside the sandbox. It never extends
that approval to `index`, `rebuild`, or skill management commands.

Some Codex surfaces, including side conversations, cannot request approval. If
the database is readable and compatible but loopback Ollama is blocked by the
sandbox, the skill uses the explicit `search --lexical` mode. This queries the
existing SQLite FTS5 index without contacting Ollama and reports that semantic
recall is unavailable; it is not used for database or embedding compatibility
errors.

The default database is `~/.lodex/history/lodex.db`. Lodex creates the data
directory with mode `0700` and the database with mode `0600`.

## Updating an existing history index

When updating a schema-v1 or schema-v2 database, run `lodex index` once before
search or show. Schema v3 preserves all chunks and embeddings and adds session
origin fields. Existing sessions start as `unknown` with provenance pending;
incremental indexing reparses pending sessions even when their files are unchanged.
Unchanged chunks reuse their embeddings. A scoped index only backfills that scope;
`status` reports how many non-missing sessions remain pending. Before migration,
`status` stays read-only and reports the old counters alongside the compatibility
error. Missing source files remain unknown until they can be read again.
