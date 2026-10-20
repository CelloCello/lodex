# Repository architecture

Lodex provides local tools for developers working with coding agents. Its CLI
exposes task environment management and session history retrieval; bundled skills
guide agent use, MCP exposes read-only history queries, and the optional Console
provides a browser interface to environment management.

The monorepo contains a shared Python workspace and a React frontend. Each
Python project uses `src` layout, declares its own runtime dependencies, and
builds its own wheel and source distribution. The root coordinates development;
it is not an installable package.

```text
lodex/
├── core/
│   ├── src/lodex_core/{management,history}/
│   ├── tests/
│   └── pyproject.toml
├── cli/
│   ├── src/lodex_cli/             # Commands, history MCP, bundled Skills
│   ├── tests/
│   └── pyproject.toml
├── console/
│   ├── f2e/                      # React source, browser tests, pnpm-lock.yaml
│   ├── server/
│   │   ├── src/lodex_console/     # HTTP app, actions, worker, generated static/
│   │   ├── tests/
│   │   └── pyproject.toml
│   └── tests/                    # CLI/Console lifecycle and browser fixture
├── examples/multi_service/       # Standalone app fixture and isolation tests
├── scripts/                      # Release and real-project validation
├── docs/
├── pyproject.toml                # Workspace, dev tools, shared check settings
└── uv.lock                       # One Python dependency resolution
```

## Dependencies and runtime

```text
Frontend ── HTTP ──> Console Server ──> Core
CLI ────────────────────────────────> Core
History MCP (in CLI package) ────────> Core history
```

Core owns management state and operations, and separately owns history indexing
and retrieval. It imports neither CLI nor HTTP/MCP frameworks. The interfaces
call Core directly; the server does not invoke or parse CLI commands. `lodex
console` lazily loads the optional server only to launch it.

Core implements SQLite connections, schemas, migrations, and transactions. CLI
and Console Server open Core's `Registry` to access the same management database;
the server does not maintain a separate database or implement SQL. Interface
code handles requests and composes responses, while shared worktree operations,
including registration removal (`forget`), live in Core. Forgetting removes only
the taskenv registration; it preserves the worktree, resource records, and shared
secrets. History uses its own database, separate from management state.

| Directory | Distribution | Import package | Runtime dependencies within Lodex |
| --- | --- | --- | --- |
| `core` | `lodex-core` | `lodex_core` | None |
| `cli` | `lodex` | `lodex_cli` | `lodex-core`; optional `lodex-console` |
| `console/server` | `lodex-console` | `lodex_console` | `lodex-core` |

Management and history live in separate Core subpackages because they have
different data and configuration. Management commands do not load Ollama or
history storage at runtime. MCP currently exposes history only. The CLI package
also owns the Skills and their installation lifecycle.

The Console's request worker is an HTTP implementation detail. Long-running
service supervision belongs to Core and survives CLI or Console shutdown.
Neither the monorepo nor its workspace introduces a required central daemon.
User data defaults to `LODEX_HOME` (`~/.lodex`) outside the repository. Management
uses `management.db` and its resource directories; history defaults to
`history/config.toml` and `history/lodex.db`, with explicit history path overrides
available. The two workflows keep separate databases and configuration contracts.
Import/package changes do not change database schemas or taskenv IDs.

## Development and tests

From the root, `uv sync --locked` installs all three workspace packages editably
and the shared development tools. Source edits are immediately available without
a user-wide installation. After changing dependency metadata, run `uv lock` and
`uv sync`.

```bash
uv run lodex --help
uv run pytest core/tests -m "not ollama"
uv run pytest cli/tests
uv run pytest console/server/tests
uv run pytest console/tests
uv run pytest examples/multi_service/tests
uv run python scripts/verify_environments.py
uv run pytest -m "not ollama"
uv run ruff check .
uv run ruff format --check .
uv run mypy
pnpm --dir console/f2e install --frozen-lockfile
pnpm --dir console/f2e run build
pnpm --dir console/f2e test
pnpm --dir console/f2e run format:check
```

Each suite owns its `conftest.py` and test helpers. Core keeps its transcript
corpus in `core/tests/fixtures`; CLI owns the four samples its history/MCP tests
exercise, plus its own small builders. Neither suite imports the other's tests.
Simple Git/registry setup is intentionally local to each suite, so fixtures do
not silently apply to unrelated projects. Product packages never include tests.

Tests belong to the interface whose behavior they verify: CLI workflows stay in
`cli/tests` even when they use Core; HTTP tests stay in `console/server/tests`.
The CLI/Console lifecycle belongs to `console/tests`, and self-contained multi-service
isolation checks belong to `examples/multi_service/tests`. The standalone acceptance
runner in `scripts/verify_environments.py` uses only the installed CLI and temporary
resources. Application-specific recipes and acceptance runners belong in each
application's `.lodex/`, outside Lodex's runtime, build and test dependencies.
Browser tests live with their Node dependencies
under `console/f2e/tests`; their Python fixture is in `console/tests`.

The root contains only the shared test/tool configuration. `pytest` uses importlib
mode and namespace-aware discovery to distinguish identically named modules such
as `core.tests.test_management` and `cli.tests.test_management`. Run all suites
with `uv run pytest`, or select a subproject's tests explicitly. Running
`uv run pytest tests` from a Python subproject also selects only its local tests.

## Build and installation

The repository uses Apache License 2.0. Each Python package keeps a byte-identical
copy of the root `LICENSE` so its wheel and standalone sdist include the license
text. Keep those copies and the package license metadata synchronized.

All three Python distributions use the same release version and exact internal
dependency versions. Update the three project versions, internal requirements,
CLI `__version__`, frontend package version/lock and installation examples
together. Regenerate `uv.lock` and validate the complete release set.

```bash
pnpm --dir console/f2e install --frozen-lockfile
uv build --all-packages
uv run python scripts/verify_distribution.py
```

The Console Server build hook rebuilds the frontend in a source checkout. The
result belongs in `console/server/src/lodex_console/static/` and is packaged in
both its wheel and sdist. Building a wheel from that sdist uses the included
assets, so recipients need no sibling frontend checkout or Node.js. Editable
workspace installation skips frontend rebuilding; run its build command after
changing UI source.

Install the CLI wheel with `dist` as the local dependency source; use `[console]`
for the optional UI. See the root README for exact commands. Distribute or
publish the complete set of related wheels, since the CLI wheel depends on Core
and the Console extra depends on Server. Installing only the CLI excludes the
Console package and its frontend resources.

The installation check runs outside the source checkout, verifies isolated Core,
CLI and Server installs, exercises the installed command and packaged Skills,
reinstalls the release, and checks the Console and service lifecycle. Reinstalling
the same release verifies data preservation, not an upgrade from every historic
release. The supported user entrypoint is `lodex`; Python modules use the package
names in the table above (`python -m lodex_cli.main` is the module CLI entrypoint).
