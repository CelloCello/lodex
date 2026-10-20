<p align="center">
  <img src="docs/assets/lodex-logo.svg" width="112" height="112" alt="Lodex logo" />
</p>

<h1 align="center">Lodex</h1>

<p align="center">
  <strong>A local toolkit for working with coding agents.</strong><br />
  Set up a checkout. Run your project. Recover earlier context.
</p>

<p align="center">
  <a href="#installation">Installation</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#guides">Documentation</a> ·
  <a href="#optional-herdr-integration">Herdr integration</a>
</p>

<p align="center">
  <strong>English</strong> · <a href="README.zh-TW.md">繁體中文</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-20332f?style=flat-square" alt="License: Apache 2.0" /></a>
  <a href="cli/pyproject.toml"><img src="https://img.shields.io/badge/version-0.3.0-20332f?style=flat-square" alt="Version 0.3.0" /></a>
  <a href="#installation"><img src="https://img.shields.io/badge/Python-3.11%2B-3776ab?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.11 or newer" /></a>
  <a href="docs/history.md#connect-codex-through-mcp"><img src="https://img.shields.io/badge/MCP-read--only_history-626b68?style=flat-square" alt="MCP: read-only history retrieval" /></a>
</p>

---

Lodex is a local toolkit for developers working with coding agents. It helps you
and your agent set up a checkout for a task, run its commands and services, and
find useful context from earlier agent sessions.

- **Set up a place to work**: register a Git repository, create or attach a
  worktree, and give that checkout its own settings and allocated ports.
- **Run and inspect the project**: run repository-defined preparation and
  verification commands, start or stop services, and inspect results and logs.
- **Recover earlier context**: search past coding-agent discussions to find
  decisions, previous attempts and supporting evidence. The bundled history
  source adapter currently reads Codex sessions.

## Use Lodex with a coding agent

The **CLI** provides the local tools. Optional **agent skills** guide your agent
in using them for project setup, worktrees, services and history retrieval.
**MCP** exposes read-only history search to an agent. The optional **Console**
lets you inspect and operate the same task environments in a browser.

For example, ask an agent to configure a repository with `lodex-project-setup`,
create a checkout with `lodex-worktree`, and start the project's services with
`lodex-services`. The agent edits code in that checkout; Lodex runs the configured
commands and keeps environment state, results and logs available across sessions.
Use `lodex-history` to look up earlier discussions when you need their context.

Start with the [first website walkthrough](docs/manual-validation.md) for a guided
agent-assisted workflow, or the [quick start](#quick-start) for direct CLI use.
See [agent skills](#agent-skills) for installation. For coordinating multiple
agents, see the [optional Herdr integration](#optional-herdr-integration).

Environment management works independently of a particular coding agent and
without Ollama. History has separate configuration and storage; indexing and
hybrid search use a local Ollama model. MCP currently exposes history retrieval
only; environment operations use the CLI or Console.

## Guides

- [Local task environments: configuration and command reference](docs/management.md)
- [Session history: indexing, filters, configuration and MCP](docs/history.md)
- [Optional local console](docs/console.md)
- [Manager/worker workflow with Herdr](docs/herdr.md)
- [First coding-agent workflow: build a small website](docs/manual-validation.md)
- [Monorepo structure, development and packaging](docs/architecture.md)
- [Self-contained multi-service fixture and isolation check](examples/multi_service/README.md)

## Installation

Use Python 3.11+ and `uv`. This repository is a workspace containing Core, CLI
and Console Server packages. Build the release set from a checkout, then install
the CLI wheel with the other wheels available as local dependencies. Building
the Console requires Node.js 20.19+ or 22.12+ and pnpm (version pinned in
`console/f2e/package.json`);
using an installed release does not.

```bash
cd /absolute/path/to/lodex
uv sync --locked
pnpm --dir console/f2e install --frozen-lockfile
uv build --all-packages
uv tool install --find-links dist dist/lodex-0.3.0-py3-none-any.whl
lodex --version
lodex --help
```

Environment management requires Git. Its process supervision and locking
currently use POSIX APIs. History setup additionally requires
[Ollama](https://ollama.com/download); see the history quick start below.

For the optional browser console, install the extra from the release set built
above. You can then start the installed console from any directory:

```bash
uv tool install --force --find-links dist 'dist/lodex-0.3.0-py3-none-any.whl[console]'
lodex console --port 8765
```

Open the complete URL printed in the terminal, including `#token=...`, and keep
the terminal running. Press Ctrl+C there to stop the console; managed services
continue running. Omitting `--port` chooses an available port automatically.

The console shares management state with the CLI and ships with compiled assets.
Normal use requires no Node.js or Vite server. The header offers System, Light and
Dark; using the same host and port preserves the browser's saved theme choice.
See the [console guide](docs/console.md) for access, navigation and lifecycle
details, and [updating the installed console](docs/console.md#update-the-installed-console)
to make checkout changes available in an installed release.

## Quick start

### Manage a local task environment

A project is a registered local Git repository. An environment (task environment,
internally `taskenv`) associates one Git worktree with settings, allocated ports,
command records and services. A worktree is the physical Git working directory;
the environment record can remain after that directory is removed.
Registering a project does not automatically register an environment for its main
worktree. See the [shared terminology](docs/management.md#terminology).
Projects can have an editable display name (`project add … --display-name TEXT`;
`project rename ID NAME`). Commands and existing environments continue using the
fixed project ID; older registrations display that ID until named.

`project add` validates and keeps an existing `.lodex/project.toml`. If it is
missing, it creates a minimal skeleton, or copies the recipe passed with
`--config PATH`. For a new skeleton, edit the file to define the repository's
commands and services before running them; see the
[configuration example](docs/management.md#version-1-configuration).
For Lodex itself, the existing bundled recipe already defines `prepare` and `verify`:

```bash
lodex project add lodex /absolute/path/to/lodex
lodex worktree attach lodex /absolute/path/to/lodex
cd /absolute/path/to/lodex
lodex context
lodex prepare
lodex run verify
```

To work in a new checkout instead, create a branch from an existing Git ref:

```bash
lodex worktree create lodex --ref main --branch feature-one --json
lodex worktree list --json
```

Creation returns the task environment ID and checkout path. It does not run
`prepare`. New directory names combine the creation branch's readable slug and
eight ID characters, such as `feature-one--a3f19c82`; existing paths stay unchanged.
The full taskenv ID remains the stable identifier, including after branch changes.
Use `--target TASKENV_ID` or an absolute checkout/subdirectory path
on target-taking commands, or run them inside the registered checkout:

```bash
lodex prepare --target TASKENV_ID
lodex run verify --target TASKENV_ID
```

Command and service names come from the checkout's recipe. For example,
`lodex service start web` needs a configured `services.web`; the Lodex recipe
above does not define services or a cleanup command.

### Search session history

Start Ollama (`ollama serve` if it is not already running), then download the
model and build the index:

```bash
ollama pull qwen3-embedding:0.6b
lodex status
lodex index
lodex search "why was the parser changed?" --project current --limit 5
lodex show CHUNK_ID --context 1
```

Run `lodex index` again for incremental refreshes. `lodex status` checks the
**history runtime and index**, not task environments; use `context`,
`worktree inspect` and `service list` for environment state.
See the [history guide](docs/history.md) for filters, lexical-only search and MCP.

## Command overview

Use `lodex <command> --help` or `lodex <command> <subcommand> --help` for options.
In examples, replace uppercase placeholders with actual IDs, names or paths.

### Environment management

| Command | Purpose |
| --- | --- |
| `project add NAME PATH`, `project list` | Register repositories, initialize missing configuration, and list registrations. |
| `worktree create PROJECT --ref REF --branch BRANCH` | Create and register a Lodex-owned checkout on a new branch. |
| `worktree attach PROJECT PATH` | Register an existing checkout without taking ownership. |
| `worktree list`, `worktree inspect` | Inspect registered environments, including missing checkouts. |
| `worktree remove`, `worktree forget` | Preview checkout deletion or deregistration; `--yes` executes. |
| `context` | Resolve the current or explicitly selected environment; require a present checkout. |
| `prepare`, `run NAME`, `cleanup` | Run the corresponding repository-defined command and record the result. |
| `service start NAME`, `service stop NAME` | Start or stop a configured service. |
| `service list`, `service inspect NAME`, `service logs NAME` | Query saved service state and recent logs. |
| `operation list`, `operation inspect ID`, `operation logs ID` | Query recorded repository command runs and recent logs. |
| `env show` | Inspect resolved TOML settings, allocated values and secret references. |
| `env export` | Write a protected dotenv file (default `.env`); may include secret values. |
| `port set KEY VALUE` | Change a declared port assignment; stop affected services first. |
| `secret list`, `secret set NAME`, `secret remove NAME` | List stored names, enter a value privately, or preview/delete a shared value; no project or taskenv required. |

Management commands support `--json`, placed after the command name. Target-taking
commands accept `--target TASKENV_ID` or an absolute directory; omission resolves
the current directory. `operation inspect/logs` take an **operation ID** instead.
Secret commands operate on the central store and do not accept `--target`.
See the [complete management reference](docs/management.md#command-reference)
for arguments and lifecycle details.

`cleanup` only runs the repository's cleanup recipe. It does not implicitly stop
services or remove a checkout. `worktree remove` deletes only a Lodex-owned
checkout and retains its branch; `worktree forget` only removes registration.

Edit ordinary values and secret mappings directly in the checkout's
`.lodex/project.toml`; there is no separate DB override layer. For example:

```toml
[env]
APP_MODE = "development"
[secrets]
API_TOKEN = "secret:app-dev-token"
```

Store the value independently with `lodex secret set app-dev-token` (hidden
input). The name is `app-dev-token`; `API_TOKEN` is the variable the application
receives. Each subsequent command/service start or `env export` resolves the
current stored value; already-running processes are not updated automatically.
`env show` does not read an existing `.env`. `env export` generates one when
needed; Lodex-managed processes receive values directly without that file.

### Session history

| Command | Purpose and example |
| --- | --- |
| `index` | Build or incrementally refresh the index: `lodex index --session SESSION_ID`. |
| `search QUERY` | Search indexed history: `lodex search "parser" --project current --limit 5`. |
| `show CHUNK_ID` | Expand a hit and neighboring turns: `lodex show CHUNK_ID --context 1`. |
| `status` | Diagnose Ollama, model and index compatibility: `lodex status --json`. |
| `rebuild --yes` | Reset the history index; run `lodex index` afterward to repopulate it. |
| `mcp` | Serve read-only history `status`, `search` and `show` over stdio for an MCP client. |

All history commands above except `mcp` support `--json`; their output format is
separate from management's `ok`/`result` envelope. More examples and filter semantics
are in the [history command reference](docs/history.md#commands).

### Agent skills

Skills provide optional agent instructions around the CLI. Install or update one
with `lodex skill install NAME`, and remove it with `lodex skill remove NAME`.
Both support `--dry-run`; omitting `NAME` selects `lodex-history`.

For an agent-driven workflow using `project add`, `lodex-project-setup`,
`lodex-worktree` and `lodex-services`, follow the [website walkthrough](docs/manual-validation.md).
It includes skill installation and prompts for setup, worktree creation, services,
logs, coding, commits and cleanup. Console is used primarily to observe shared state.

| Skill | Purpose |
| --- | --- |
| `lodex-history` | Search prior session evidence through MCP or the CLI. |
| `lodex-worktree` | Create, attach, inspect and remove task environments through the CLI. |
| `lodex-services` | Operate task environment services and inspect their state and logs. |
| `lodex-project-setup` | Set up a repository's `.lodex/project.toml` recipe. |
| `lodex-herdr` | Optional: coordinate agents through Herdr in Lodex-owned taskenvs. See [Herdr integration](#optional-herdr-integration). |

```bash
lodex skill install lodex-worktree --dry-run
lodex skill install lodex-worktree
```

Skills are installed as managed copies, so moving or deleting the source checkout
does not break them. Reinstalling an identical copy makes no change; an update
replaces the whole installed skill, including local edits and stale files.
For history MCP setup, see [Connect Codex through MCP](docs/history.md#connect-codex-through-mcp).

## Optional Herdr integration

For work involving multiple coding agents, you can combine Lodex with Herdr.
A manager agent can prepare a separate task checkout for each worker, delegate
work and collect results. Lodex manages the checkouts and services; Herdr provides
the panes and agent processes. The `lodex-herdr` skill guides the manager through
this workflow, connecting environment preparation with worker launches and follow-up.
Lodex's CLI, Console, history tools and other skills work independently of Herdr.

Keep the manager in the source repo and give each worker its own task checkout.
For Codex, the suggested config names are `lodex-manager` and `lodex-worker`;
these are config profiles, not Lodex commands or services. You start the manager
with its profile; the manager then follows the skill to launch workers with theirs.
Installing a skill does not configure or restart an agent.

Follow the [Herdr guide](docs/herdr.md) for role setup, an optional
manager shortcut, dispatch, verification and cleanup. Keep Herdr's own skill
installed for current CLI and interactive agent handling. The bundled
[integration skill](cli/src/lodex_cli/bundled_skills/lodex-herdr/SKILL.md) and
[Codex setup reference](cli/src/lodex_cli/bundled_skills/lodex-herdr/references/codex.md)
provide the detailed agent instructions and permission templates.

```bash
lodex skill install lodex-herdr --dry-run
lodex skill install lodex-herdr
```

## Configuration and storage

| Workflow | Configuration | Default data location |
| --- | --- | --- |
| Environment management | Each checkout's `.lodex/project.toml`; allocated ports and central secrets in the registry | `~/.lodex/management.db`, logs and service handles under `~/.lodex` (`LODEX_HOME`) |
| Session history | `~/.lodex/history/config.toml` (`LODEX_CONFIG`) | `~/.lodex/history/lodex.db` (`LODEX_DATA_DIR` / `LODEX_DB_PATH`) |

`LODEX_HOME` changes the default root for both workflows (default `~/.lodex`).
History reads `$LODEX_HOME/history/config.toml` when present and stores its index
under `$LODEX_HOME/history/`. Explicit history path overrides take precedence;
see [history configuration](docs/history.md#configuration) for the resolution rules.

Management secrets are stored **in plaintext SQLite**, with private file
permissions on POSIX. There is no encryption, key file or OS keychain dependency.
Treat the management DB and its backups as sensitive. Environment queries expose
references; `secret list` lists stored names only.
`secret set` accepts hidden terminal input or `--stdin`, never a value argument.
See [management configuration](docs/management.md#version-1-configuration) for
shared references, export protections and configuration editing.

History reads source transcripts without modifying them. Embeddings use a
loopback-only Ollama endpoint and the derived index stays local. See
[history configuration](docs/history.md#configuration) and
[privacy and automation](docs/history.md#privacy-and-automation) for details.

## Update or remove an installation

Rebuild the release set from the checkout, reinstall it, then update each skill
you use. Add `[console]` to the wheel argument to keep the optional console:

```bash
cd /absolute/path/to/lodex
uv sync --locked
pnpm --dir console/f2e install --frozen-lockfile
uv build --all-packages
uv tool install --force --reinstall --find-links dist dist/lodex-0.3.0-py3-none-any.whl
lodex skill install lodex-history --dry-run
lodex skill install lodex-history
```

For an installation with Console, replace the `uv tool install` command above with:

```bash
uv tool install --force --reinstall --find-links dist 'dist/lodex-0.3.0-py3-none-any.whl[console]'
```

The installed console serves the assets bundled in its Server wheel. Editing the
checkout or running only the frontend build does not update that installation.
After reinstalling, stop any old console process with Ctrl+C, run
`lodex console --port 8765` again, and open its newly printed token URL.

For existing history databases, check the
[index upgrade instructions](docs/history.md#updating-an-existing-history-index).
The management guide describes its own schema upgrades separately.

Remove an installed skill or the CLI with:

```bash
lodex skill remove lodex-history --dry-run
lodex skill remove lodex-history
uv tool uninstall lodex
```

Removing the CLI or a skill does not clean up managed environments, databases,
logs or source transcripts. Stop services and perform any intended environment
cleanup before uninstalling the CLI.

## Development

Create or synchronize the project environment, then run Lodex through the
checkout. Development does not require a user-wide tool installation.

```bash
uv sync --locked
uv run lodex --help
```

Workspace packages are installed editably into the root `.venv`. Use the wheel
installation above for an isolated CLI available from other projects. The root
is a workspace coordinator, not an installable Python package.

Run the local validation suite from the checkout:

```bash
uv run pytest -m "not ollama"
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

The CLI uses Typer in `cli/src/lodex_cli/`. Both it and the HTTP server in
`console/server/src/lodex_console/` call `core/src/lodex_core/`. The frontend
lives in `console/f2e/`. Each subproject owns its tests, fixtures and test helpers.
Console lifecycle tests live in `console/tests/`, and multi-service isolation tests
live in `examples/multi_service/tests/`. Run `uv run python scripts/verify_environments.py`
for the standalone CLI acceptance flow, without another repository or Docker. See the
[architecture guide](docs/architecture.md) for dependency boundaries and commands.
History runtime dependencies load only when a history command runs.

The real Ollama contract test is marked separately:

```bash
uv run pytest -m ollama core/tests/test_ollama_integration.py
```

## License

Lodex is licensed under the [Apache License 2.0](LICENSE).
