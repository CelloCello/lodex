# Lodex Core

Shared Python library for local task environments and coding-agent history.

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
