---
name: lodex-project-setup
description: Connect a repository to Lodex by inspecting local evidence, drafting project.toml and testing explicit environment commands. Use for initial setup or configuration changes, including repositories with no services.
---

Inspect applicable AGENTS.md, configuration readers, existing scripts and Compose
files before editing `.lodex/project.toml`. Reuse evidence-backed commands; ask
about unresolved credentials, isolation requirements or destructive effects before
dependent trials. A repo without services needs only prepare/verify.

Lodex manages taskenv registration, worktree operations, ports and processes. Repo
scripts own provisioning, migrations, backups and application configuration,
including whether to use files or only injected settings. Check existing scripts
for overlapping lifecycle ownership. Verify DB/queue isolation with test data,
not merely different ports.

Keep new integration scripts/support files under `.lodex/`; reference suitable
existing scripts in place. Include integration files in the Git ref used for new
worktrees, with narrow ignores for runtime state and secrets. Preserve user edits.
`project add` creates a missing TOML skeleton, or copies `--config PATH`; existing
files are validated and kept. Configuration fallback copies only missing TOML;
Git checkout supplies tracked files normally. Updating the source does not refresh
existing taskenvs; preserve local configuration and ownership records when applying updates.

Draft schema version 1 TOML using these supported fields:

```toml
schema_version = 1
tools = ["python3"]
[env]
ENV_NAME = "task-${LODEX_TASKENV_ID}"
[ports]
PORT = 0
[secrets]
API_TOKEN = "secret:project-api-token"
[commands.verify]
argv = ["python3", ".lodex/scripts/verify.py"]
scripts = [".lodex/scripts/verify.py"]
[services.web]
argv = ["python3", ".lodex/scripts/server.py"]
scripts = [".lodex/scripts/server.py"]
ready_port = "PORT"
url = "http://127.0.0.1:${PORT}"
```

This example requires real scripts. `argv` executes without an implicit shell;
declare script dependencies in `scripts` and executables in `tools`. `${NAME}`
interpolates taskenv inputs; secrets belong in process env, never argv or public URLs.
Port `0` requests a saved allocation. Every service is a managed process with
`argv`; shared dependencies use connection settings, not `external` service entries.

Use either `ready_port` or a short, read-only `ready_argv` probe (exit 0 means ready;
one second per attempt). `ready_timeout` defaults to 10 seconds; `stop_timeout`
defaults to 3 and should cover application shutdown. Both accept >0 through 300.
Probes can read `LODEX_SERVICE_PID` and `LODEX_SERVICE_STARTED_AT` from process env
to reject stale readiness. These fields require a supporting CLI/Console build;
running services keep their launch configuration. Repo commands retain a fixed
three-second interrupt grace.

Register and attach before trialing authorized actions. `lodex run NAME` executes
the repo-defined `[commands.NAME]`; registration does not start services:

```
lodex project add NAME /absolute/repo --json
lodex worktree attach NAME /absolute/repo --json
lodex env show --target ID --json
lodex prepare --target ID --json
lodex run verify --target ID --json
lodex operation logs OPERATION_ID --json
```

Use checkout `[env]` values and `[secrets]` mappings; there is no separate registry
override layer. `env show` previews Lodex inputs, not application files. For secret
values, ask users to use `lodex secret set NAME` with hidden input or trusted stdin;
keep values out of chat, argv and tracked files. The store is plaintext SQLite
under `LODEX_HOME`; protect it and its backups. Identical `secret:NAME` references
within one management DB share a value. Changes affect future starts/exports;
cleanup does not delete secrets. Optional `env export` writes dotenv, rejects
tracked/modified files and requires ignored secret output.

Scripts may report UTF-8 JSON through `LODEX_RESULT_FILE`. Each `resources` entry
has name, kind, id, scope (exclusive/shared) and state (present/removed/unknown);
top-level `urls` contains HTTP(S) strings. Report actual trials, observed resources
and taskenv ID/path. Inspect interrupted/unknown operations before retrying;
missing cleanup scripts require restoration or explicit manual handling.
