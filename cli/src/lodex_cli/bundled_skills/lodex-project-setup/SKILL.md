---
name: lodex-project-setup
description: Configure Lodex integration on explicit request or within the same authorized task. Default ordinary project setup to the current repo's existing tools.
---

Work in the current repo/checkout by default. Configure Lodex only on explicit
user request or within the same authorized task, retaining its original
environment and operation scope. Installed tools or `.lodex` files do not
authorize activation. Recipe edits/reviews alone do not authorize registration,
attachment, checkout creation, `prepare` or service startup; these require a
requested live setup/trial.

Inspect applicable AGENTS.md, README, configuration loaders, existing scripts and
Compose files before editing `.lodex/project.toml`. Preserve established choices;
ask about unresolved settings delivery, sharing or destructive effects before
dependent trials. Create only the integration needed for the requested use.

Lodex manages taskenv identity and the ports, processes and secrets the project
chooses to entrust to it. Repo scripts own provisioning, migrations, backups and
application settings. Setup works without Herdr or an agent profile.

## Establish the project contract

- Identify which DBs, queues, directories and external endpoints are shared or
  taskenv-specific. Sharing the same DB or data is valid; record expected visibility
  and the impact of migrations/reset. Use test data to verify the chosen behavior.
- Identify who starts/stops each process. A Lodex-managed service must stay in the
  foreground under supervision. A command that starts a detached service and exits
  is a project-owned lifecycle; preserve its explicit stop/cleanup mechanism and
  report any gap in Lodex/worker control. Shared external dependencies can remain
  connection settings, with their existing owner.
- Choose how a new checkout receives settings: project-managed files/loaders,
  an existing secret tool, Lodex inputs, or a declared combination. The source
  checkout's ignored `.env` is not automatically copied, and Lodex commands do not
  inherit arbitrary project credentials from the caller's shell. Establish the
  authorized source, loading time, missing-input behavior and refresh procedure.
- Cleanup must follow resource ownership. Removing one taskenv must preserve shared
  resources unless the user has authorized that shared-resource action. Explicitly
  shared data may be affected by normal work as agreed; separate ports alone do
  not establish data isolation.

Keep new integration scripts/support files under `.lodex/`; reference suitable
existing scripts in place. Include integration files in the Git ref used for new
worktrees, with narrow ignores for runtime state and secrets. Preserve user edits.
When the user wants live read-only directories from the registered source checkout,
declare top-level `readonly_dirs` in both the source and task recipe (the usual
config copy suffices). Use the user's selected directory names; the default shares
none. Create source directories before prepare and use the generated worker policy.
`project add` creates a missing TOML skeleton, or copies `--config PATH`; existing
files are validated and kept. Configuration fallback copies only missing TOML;
Git checkout supplies tracked files normally. Updating the source does not refresh
existing taskenvs; preserve local configuration and ownership records when applying updates.

## Write the minimum integration

Use supported schema version 1 fields; keep agent/runtime/permission selection in
the coordination workflow. Record resource ownership and loading details in the
existing recipe/scripts or concise project documentation; no new schema is needed.

This example opts into a managed web process, allocated port and Lodex secret.
Include those parts only when the project chooses them; replace scripts with
observed project commands or real integration scripts:

```toml
schema_version = 1
tools = ["python3"]
[env]
ENV_NAME = "task-${LODEX_TASKENV_ID}"
[ports]
PORT = 0
[secrets]
API_TOKEN = "secret:project-api-token"
[commands.prepare]
argv = ["python3", ".lodex/scripts/prepare.py"]
scripts = [".lodex/scripts/prepare.py"]
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
Port `0` requests a saved allocation for a taskenv listener. Shared endpoint ports
belong in connection settings, not `[ports]` allocations. Every service entry is
a managed process with `argv`; shared dependencies use connection settings, not
`external` service entries.

Define only needed operations. The agent-dispatch workflow requires a successful
`commands.prepare` for its handoff; when no setup is needed, use an explicit
side-effect-free prepare with an already available project tool. A project without
services needs no service entries or controller. Verify commands follow the
project's actual checks.

Use either `ready_port` or a short, read-only `ready_argv` probe (exit 0 means ready;
one second per attempt). `ready_timeout` defaults to 10 seconds; `stop_timeout`
defaults to 3 and should cover application shutdown. Both accept >0 through 300.
Probes can read `LODEX_SERVICE_PID` and `LODEX_SERVICE_STARTED_AT` from process env
to reject stale readiness. These fields require a supporting CLI/Console build;
running services keep their launch configuration. Repo commands retain a fixed
three-second interrupt grace.

## Validate and hand off

Registration, prepare and central secret management need management access. In a
restricted B/C session, return proposed recipe changes and trial needs to A for
review/preparation and grant renewal; keep the worker's execution boundary intact.

For a user-requested live Lodex setup/trial, register and attach if needed before
trialing authorized actions. For recipe-only work, validate configuration and
scripts without activating a taskenv. Run only declared commands and authorized
trials. `lodex run NAME` executes the repo-defined `[commands.NAME]`;
registration does not start services:

```
lodex project add NAME /absolute/repo --json
lodex worktree attach NAME /absolute/repo --json
lodex env show --target ID --json
lodex prepare --target ID --json
lodex run verify --target ID --json
lodex operation logs OPERATION_ID --json
```

Use checkout `[env]` values and `[secrets]` mappings when selecting Lodex-managed
inputs; there is no separate registry override layer. `env show` previews those
inputs, not application files. A project's own `.env`/secret tool can remain its
settings source without migrating values into Lodex. For Lodex secret values,
ask users to use `lodex secret set NAME` with hidden input or trusted stdin;
keep values out of chat, argv and tracked files. The store is plaintext SQLite
under `LODEX_HOME`; protect it and its backups. Identical `secret:NAME` references
within one management DB share a value. Changes affect future starts/exports;
Lodex does not automatically delete stored secrets during cleanup. Optional
`env export` writes dotenv, rejects tracked/modified files and requires ignored
secret output.

`[taskenv] env_file = ".env"` explicitly selects Lodex export; it does not merely
declare that the app uses dotenv. Use it only when the project wants Lodex to
generate that output, and ensure the app loads it. `prepare` exports before its
command, using tracked/ignored/modified-file protections; the parent must already
exist. Omit it for a project-owned file/loader or recipe-generated settings. Do not
overwrite handwritten settings or create a second competing source of truth.
Successful prepare returns a secret-free handoff snapshot for a new agent;
create/present state alone does not establish readiness, and retries reuse the ID.

Scripts may report UTF-8 JSON through `LODEX_RESULT_FILE`. Each `resources` entry
has name, kind, id, scope (exclusive/shared) and state (present/removed/unknown);
top-level `urls` contains HTTP(S) strings. Report actual trials, observed resources
and taskenv ID/path. Inspect interrupted/unknown operations before retrying;
missing cleanup scripts require restoration or explicit manual handling.

Report settings delivery, shared/exclusive resources and their lifecycle owners,
actual commands/results, and any required paths/hosts/tools. Distinguish project
startup validation from restricted-agent validation. The coordination workflow
checks actual B/C permissions and autonomous service operations; this skill does
not launch agents or claim that manager-side success proves worker compatibility.
