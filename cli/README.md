# Lodex CLI

The command-line entry point for Lodex, a local toolkit used alongside coding
agents. Developers and agents use it to manage task checkouts, run repository
commands and services, and retrieve earlier session context. It also packages
optional agent skills and the read-only history MCP interface.

See the [main README](../README.md) for the workflow, installation and quick start.

The `lodex` Python distribution provides the `lodex` command. Its import package
is `lodex_cli`; it depends on `lodex-core`, with `lodex-console` available through
the `console` extra.

- `src/lodex_cli/main.py`: command registration and optional Console launch.
- `management.py`, `history.py`, `support.py`: typed commands and output handling.
- `mcp_server.py`: the read-only history adapter launched by `lodex mcp`.
- `skill_install.py`, `bundled_skills/`: packaged agent instructions and installer.
- `tests/`: command routing, management CLI workflows, history CLI, MCP and Skill
  installation tests. Fixtures, transcript samples and helpers belong to this
  directory; they do not import Core's test suite.

Run `uv run pytest cli/tests` from the repository root. CLI commands call Core
directly; launching Console is the only optional dependency on its server.
See [the architecture guide](../docs/architecture.md) for development and packaging.
