# Self-contained multi-service fixture

This fixture validates the environment tools that developers and coding agents
use through Lodex: preparing separate task checkouts, running their services,
inspecting results and cleaning up. See the [main README](../../README.md) for
the overall workflow, or the [first website walkthrough](../../docs/manual-validation.md)
to try Lodex with a coding agent.

This example exercises Lodex without another application repository, Docker or
third-party services. It uses Python's standard library: two loopback HTTP servers,
one worker, a SQLite application database and a separate SQLite queue. Each taskenv
keeps its own data under `.lodex/state/`, excluded by the local ignore file.

The example files become a temporary repository's integration files:

```text
.lodex/
├── project.toml
├── .gitignore
└── scripts/fixture.py
```

The repository script owns prepare/verify/cleanup and resource observations.
Lodex owns IDs, allocated ports, injected settings/secrets, operation records,
service supervision and worktree lifecycle. The worker consumes queued items and
writes their results into its own taskenv's database. The queue is an intentionally
small test implementation, without durable job-delivery or crash-recovery guarantees.

From the Lodex checkout:

```bash
uv run python scripts/verify_environments.py
uv run pytest examples/multi_service/tests
```

To validate a particular installed release, pass
`--lodex /absolute/path/to/lodex` to the runner. The runner calls only the public
CLI. It creates its own temporary Git repository, two branches/worktrees,
management registry and synthetic API token. It does not register this checkout
in the user's registry or use personal credentials.

The acceptance run verifies:

- Both environments prepare and verify, with distinct IDs and ports.
- Removing A's database makes verify fail with a saved exit code and logs; an
  explicit prepare followed by verify restores it.
- Each environment starts an API, queue and worker, and its HTTP health responses
  identify the right taskenv. New CLI processes inspect and operate these services.
- A's database write and queue/worker result are absent from B.
- Stopping and cleaning A preserves B's HTTP services and pending queue item;
  restarting B's worker processes that item.
- Cleanup reports removed resources, and owned worktrees can then be removed.

Loopback HTTP probes bypass caller and system proxy settings. On failure, the
finally block attempts to stop every recorded fixture service, even if another
service fails to stop or times out. It preserves data and the worktree for an
environment with stop failures, while still cleaning the other environment.
Failed runs retain the isolated directory for inspection; successful runs remove
it. The pytest suite also checks these failure paths, owner validation and that
verify does not recreate a missing database.

These checks establish the tested Lodex contracts with this fixture. Application
repositories own their actual service recipes and integration acceptance under
their own `.lodex/`; this fixture does not certify their migrations, external
services, production behavior or arbitrary resource isolation.
