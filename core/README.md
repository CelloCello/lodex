# Lodex Core

The shared Python library behind Lodex's tools for working with coding agents.
It manages local task environments and retrieves coding-agent session history;
the CLI exposes both workflows, MCP provides history queries, and the optional
Console provides environment management.
See the [main README](../README.md) for the user workflow and installation.

- `src/lodex_core/management/`: project recipes, worktrees, SQLite registry,
  settings, secrets, foreground operations and independent service supervision.
- `src/lodex_core/history/`: source adapters, parsing, indexing and retrieval.
- `tests/`: core behavior tests, local `conftest.py`, transcript samples in
  `fixtures/`, and builders in `support/`. These do not import other projects' tests.

Core does not import CLI, HTTP or MCP adapters. Management and history keep
separate configuration and storage. Management does not load history runtime
dependencies when it runs.

From the repository root, run `uv run pytest core/tests -m "not ollama"`.
See [the architecture guide](../docs/architecture.md) for workspace development.
