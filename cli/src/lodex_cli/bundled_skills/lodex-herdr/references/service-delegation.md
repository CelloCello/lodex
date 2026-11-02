# Optional worker service control

Use this when the user authorizes a worker to manage services in its own taskenv.
The baseline worker profile has no such grant; do not change it implicitly.

After preparing the taskenv and reviewing its recipe, the manager starts a
foreground endpoint in a manager-controlled terminal:

```bash
lodex service delegate --target TASKENV_ID --service NAME --json
```

Repeat `--service` for each authorized service. Keep the endpoint running. Its
initial result supplies an ID, credential path, Unix socket and runtime root;
do not print or forward the token itself. The grant captures the recipe/secret
references; changed recipes require a new grant, application-code edits do not.

Review a worker launch configuration that provides the credential path through
`LODEX_SERVICE_DELEGATION`, permits writes only to its checkout and grant runtime,
and permits the grant socket and its own service sockets. Protect central state
and other credentials/runtime paths from reads and writes. A broad Lodex-root or
localhost grant is not an equivalent boundary. Present concrete paths and obtain
confirmation before applying permissions. Check inherited tools/cache grants too.

With those permissions validated, workers use ordinary `lodex service`
start/stop/list/inspect/logs against their assigned taskenv.
Use `service list --json` without a target to inspect its saved services; skip
`lodex context`, which requires registry access. Services and probes
execute in the worker's permissions. The manager endpoint authorizes and records;
it never runs checkout code. Do not delegate preparation, arbitrary repo commands,
cleanup, secrets, port allocation, Git writes or Herdr control through this API.

The same credential lets any holder reach its grant, so protect both credential
read access and socket access. Environment variables are routing, not a sandbox.
For Codex, validate the actual agent's filesystem and Unix-socket rules; a passing
`codex sandbox` helper probe alone does not establish equivalent agent settings.

The manager can revoke with `lodex service revoke DELEGATION_ID --json` or close
the foreground endpoint. Subsequent worker requests fail without registry
fallback; already issued launches/services may continue. The manager can inspect
and stop them through normal Lodex commands. Revoke a stale grant after an
unhandled controller exit before replacing it; inspect unknown launches first.
Delegated operations require the original checkout to remain present and unchanged
in identity; manager stop can use the saved handle even when the checkout is gone.
After cleanup, the supervisor waits for its terminal result to be recorded and
acknowledged. Read-only queries may leave it idle; manager stop/start or delegated
inspect can collect it. Worker-written terminal states cannot authorize replacement.
Pending ACKs retain independent launch results across restarts and remain visible
in service warnings. The manager can run `service retry-acks NAME --target ID --json`
without stopping the replacement service; workers report these pending items.
