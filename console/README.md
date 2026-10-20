# Lodex Console

The optional browser interface for inspecting and operating the local task
environments you use with a coding agent. It shares environment state, command
results and service logs with the CLI, so you can follow work performed through
agent skills and take actions yourself. Session history retrieval uses the CLI
or MCP. See the [main README](../README.md) for the overall workflow.

- `f2e/`: React/TypeScript application, Vite configuration, Node dependencies and
  browser tests.
- `server/`: the optional `lodex-console` Python distribution and HTTP tests.
- `tests/`: CLI/Console lifecycle tests with local pytest fixtures, and the
  temporary CLI-created Python fixture for browser integration tests.

The frontend calls the HTTP server, which uses `lodex-core` directly. The server
does not import the CLI. Integration fixtures use both interfaces to verify the
shared management state.

See [console usage](../docs/console.md) and [architecture](../docs/architecture.md).
