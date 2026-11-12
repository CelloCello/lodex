# Delegate service control to one taskenv

[Back to management](management.md#commands-and-services)

A manager can authorize a worker to start, stop, inspect and read logs for named
services in one registered taskenv. The worker does not open the management DB.
The manager endpoint reserves launches and records observations; the worker's CLI
launches the supervisor, service and readiness probes under its own execution
permissions. The endpoint never executes repository code.

## Manager

Prepare the taskenv and inspect its recipe before delegating. Run this in a
manager-controlled terminal and keep it running:

```bash
lodex service delegate --target TASKENV_ID --service web --service worker --json
```

The initial result includes the delegation ID, credential file, Unix socket and
private runtime root. It does not print the credential's token. Explicitly select
services; there is no default grant for all services or projects. One active
delegation is allowed per taskenv. No system daemon or automatic restart is added.

The grant captures the current recipe, including its secret references. Starts
resolve current values for those approved references. A changed recipe needs a
new delegation; ordinary application-code edits do not. The grant does not
authorize arbitrary repository commands, preparation, cleanup, secret management,
port changes, Git writes or worktree operations.

## Worker

Provide the returned credential path in that worker session's environment:

```bash
export LODEX_SERVICE_DELEGATION=/absolute/returned/runtime/client.json
lodex service start worker --target TASKENV_ID --json
lodex service list --target TASKENV_ID --json
lodex service inspect worker --target TASKENV_ID --json
lodex service logs worker --target TASKENV_ID --json
lodex service stop worker --target TASKENV_ID --json
```

The endpoint binds authorization to its taskenv and selected service names;
changing `--target`, cwd or request fields cannot expand that grant. The CLI
rejects registry commands in delegation mode. An invalid credential, inactive
endpoint or unavailable control handle fails closed, without falling back to
direct registry access or signalling a saved PID.

## Sandbox boundary

Credentials confer authority to whoever can read them **and** reach their socket.
Delegation does not configure a sandbox or authenticate a Herdr pane/agent name.
Before use, review narrowly scoped permissions for the worker and all execution
tools it can access:

- Write its assigned checkout and the returned runtime root.
- Read/connect the returned manager socket; bind/connect service sockets only
  inside its own runtime root.
- A selected service with `allow_local_binding = true` gets local TCP binding,
  independently of whether readiness uses `ready_argv` or `ready_port`.
  When omitted, `ready_port` retains its existing binding inference; explicit
  `false` disables it. Worker policy uses the approved snapshot; it is not a
  per-port firewall. Application host access still needs an explicit allowlist.
- Deny central state and unrelated control sockets. New workspaces and peer
  runtimes are read-only; only assigned paths are writable. Peer credential
  visibility does not grant access to its socket: keep the Unix allowlist scoped
  to this grant and its own service runtime.

Do not grant write access to all of `~/.lodex`, use another worker's credential,
or reuse the Console's administrative token. An environment variable alone is
not a security boundary: removing delegation mode must still leave central
state inaccessible under the OS sandbox. Profiles with broad reads or shared
writable caches/temp directories require separate review. Application network
access and DB/queue/external-resource isolation remain project responsibilities.

The manager pins service control credentials outside the worker-writable runtime.
Status/log reads reject replaced roots, symlinks, hardlinks and non-regular files;
worker observations cannot replace service identity or control metadata.
Manager lifecycle checks use the pinned control handle, not worker-written
terminal states. An unverifiable launch stays unknown and cannot be replaced.

## Revoke and recover

```bash
lodex service revoke DELEGATION_ID --json
```

Revocation or closing the foreground controller rejects subsequent worker
requests. Already issued launches may finish; existing services are not stopped.
This revokes the API grant, not OS permissions or settings already delivered.
Their records and private observations remain available for ordinary manager
`service inspect`, `logs` and `stop`, including after delegation ends.
For new environments these observations are under the saved workspace root;
manager control handles remain under `LODEX_HOME`. Renewing a grant uses that
task's saved root even if the default root changed. Existing services keep their
old pinned handles until stopped/acknowledged; renewal never moves a live service.

New delegated launches default `TMPDIR` to `GRANT_RUNTIME/t`, inside their
existing filesystem and Unix-socket allowance, rather than inheriting the
controller's global temp directory. The worker creates it under its own sandbox.
An explicit project `TMPDIR` remains authoritative and must fit the reviewed
worker scope. Running services retain their original environment. The short
name leaves room for application-generated Unix socket names; those still must
fit the platform's socket-path limit.

After cleanup, a delegated supervisor retains its control socket until the manager
records its terminal result and acknowledges it. `stop`, a subsequent `start`, or
delegated `inspect` performs that recording; read-only manager queries and service
lists can leave an idle supervisor waiting. Each result is saved independently
by launch before ACK or replacement of the current service record. Failed ACKs
remain in `pending_acks` with a warning across restarts and service queries; they
do not block a new launch. To retry them without stopping the current service,
the manager runs:

```bash
lodex service retry-acks NAME --target TASKENV_ID --json
```

This only sends ACKs for retained terminal results in that taskenv/service.
`acknowledged` lists confirmations completed by this attempt; `pending_acks`
lists unresolved launches. Repeating it after completion is a no-op. Workers
cannot call it through delegation. Read-only queries do not retry, and there is
no background retry process. Unavailable or unconfirmed ACKs remain recorded,
even if the supervisor may already have exited; no PID fallback is used.

The control channel reports supervisor observations, not
proof against a worker deliberately replacing its own supervisor or spawning
other processes. Revocation does not remove its existing OS capabilities.

Delegated requests require the original checkout to remain present with the same
identity. If it is missing or replaced, ask the manager to use ordinary service
commands; manager stop uses the saved handle without requiring the checkout.

If a controller was killed without cleanup, revoke its saved ID before creating
a replacement. Inspect interrupted/unknown launches before retrying. Do not
delete runtime files while their services may still be running.

For persistent interactive workers, grant replacement also changes the paths that
the agent's sandbox must allow. Stop/confirm the affected worker, render a new
`worktree worker-config` using the new grant, then resume the same native session
and taskenv with those settings. Existing services retain their original pinned
handles until stopped; they are not relocated into the new runtime. A changed
credential does not update an already-running agent's permissions. Keep the peer
taskenv untouched. See [session lifecycle](../cli/src/lodex_cli/bundled_skills/lodex-herdr/references/lifecycle.md).

Repo cleanup is outside the service grant. Run it under taskenv permissions,
including after agent exit via `lodex cleanup --target ID --worker-policy PATH`.
The manager records results while a restricted runner executes the recipe; plain
`cleanup` still uses caller permissions. The restricted path checks project secret
references against the prepared handoff before resolving them; changed secret
scope requires review and preparation of a new policy. Project variables and
secrets enter the sandboxed command through its private input pipe; the outer
launcher uses trusted management inputs so loader variables cannot run repo code
before sandboxing. Cleanup failure does not authorize an administrative retry,
revoke or environment removal. Complete project cleanup,
service stop and terminal recording/ACK before explicitly ending the controller.

## Verification

The unit/CLI suites use disposable taskenvs to test scope enforcement, malformed
requests/replies, recipe/secret races, forged terminal states, durable terminal
receipts, revocation and manager takeover.
An opt-in macOS test also runs a worker through the installed Codex sandbox helper:

```bash
LODEX_TEST_SANDBOX=1 uv run --no-sync pytest -q cli/tests/test_service_delegation.py
```

It uses command-line-only permissions, protects central/peer fixture paths, and
checks that service children inherit file, socket and signal restrictions. It does not edit
installed profiles. A passing helper test does not prove that an existing agent
session loaded equivalent settings. Validate the intended agent configuration
before relying on it; report unsupported sandbox runtimes as unverified.
