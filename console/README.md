# Lodex Console

- `f2e/`: React/TypeScript application, Vite configuration, Node dependencies and
  browser tests.
- `server/`: the optional `lodex-console` Python distribution and HTTP tests.
- `tests/`: CLI/Console lifecycle tests with local pytest fixtures, and the
  temporary CLI-created Python fixture for browser integration tests.

The frontend calls the HTTP server, which uses `lodex-core` directly. The server
does not import the CLI. Integration fixtures use both interfaces to verify the
shared management state.

See [console usage](../docs/console.md) and [architecture](../docs/architecture.md).
