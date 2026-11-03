---
name: lodex-services
description: Start, inspect, read logs and stop Lodex-managed taskenv services in management or delegated worker sessions. Use existing project configuration for local service lifecycle operations.
---

Operate services the taskenv owns and is authorized to stop/restart. Shared DBs
or other external dependencies may be connection settings owned elsewhere; follow
the project's sharing contract and leave their lifecycle with that owner. A
detached project-owned process is not automatically controlled by service stop.

With `LODEX_SERVICE_DELEGATION` set, skip `lodex context`: it needs registry access.
Use an authorized service name from the assignment and recipe.
`lodex service list --json` shows saved records within the grant; inspect a service
when its record exists. Omit `--target` or use the assigned taskenv ID/path.
Recipe changes require a new grant.

Otherwise resolve the directory with `lodex context --target /absolute/path --json`,
or use the user's explicit taskenv ID. Inspect `.lodex/project.toml` for named
services. Commands accept `--target ID` or an absolute directory:

```
lodex service start NAME --target ID --json
lodex service list --target ID --json
lodex service inspect NAME --target ID --json
lodex service logs NAME --target ID --json
lodex service stop NAME --target ID --json
```

Restart is stop then start; confirm the stop result before starting again. Ordinary
application code edits can use the existing grant. Recipe changes need management
review and a new grant, not broader worker permissions.

Delegation only covers its taskenv/services. The worker launches services/probes
under its own permissions without opening the registry. Report denied/unavailable
delegation to the manager; never change grants, unset delegation or switch profiles
to bypass it. Other Lodex management operations remain undelegated.
In the A/B/C workflow, report an unavailable controller or changed grant to A for
coordinated renewal and native-session resume with new permissions; do not start
another writer or replay an uncertain request. The controller belongs to active
taskenv use, not one agent turn. A completed turn does not revoke it or stop services.

Manager starts execute repo code with caller permissions. For worker-modified code,
retain worker-side execution or an equivalent restricted runner; a manager start
is not a fallback for a denied delegated start.

Inspect before starting, including after switching callers; CLI/Console exit does
not stop services. `ready_port` checks TCP; `ready_argv` exit 0 means startup-ready.
Without either, running means only that the process survived startup. Readiness
is not monitored continuously. Report readiness, URL, observation time and failures.

Manager starts read current configuration. Manager stop uses the saved handle and
launch-time `stop_timeout` even without the checkout. Delegated operations require
the assigned checkout to remain present and unchanged in identity; otherwise ask
the manager to stop it. Older records default to three seconds. Allow that grace
before declaring stop unknown. Inspect interrupted starts/unknown handles before
retrying; never kill a process from a saved PID/port
alone or edit the management DB. Resolve missing configuration, scripts or secrets
before retrying; keep secret values out of argv/output. Repo cleanup and worktree
removal are separate operations; Lodex cannot stop external endpoints.

Delegated terminal states come from the pinned control handle, not the worker's
status file. The supervisor waits after cleanup until the manager records and
acknowledges the result. Without a recorded terminal result, failed verification
leaves the launch unknown and blocks restart. Failed ACKs retain independent
launch results across restarts; `pending_acks` and a warning remain on service
results. Ask the manager to run `lodex service retry-acks NAME --target ID --json`;
it only retries retained ACKs, without stopping the current service. Check the
returned `pending_acks`; an attempted retry may still be unresolved. Read-only
queries do not retry and may leave an idle supervisor waiting.
