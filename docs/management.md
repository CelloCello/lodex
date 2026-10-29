# Local task environments

[Back to README](../README.md)

Lodex's environment tools give you and your coding agent a shared way to prepare
task environments, run repository commands and manage services. Use the CLI directly
or let an agent call it through the bundled project-setup, worktree and services
skills. Environment state and logs remain available when you change callers or
start another agent session.

## Terminology

| Term | Meaning |
| --- | --- |
| Project（專案） | A registered local Git repository, identified by a project ID. |
| Environment / task environment（任務環境） | Lodex's registration associating one Git worktree with settings, allocated ports, services and operation records. `taskenv` is the internal/API name and the stable environment ID is also called a taskenv ID. |
| Git worktree（Git 工作目錄） | The physical working directory, either the repository's main worktree or a linked worktree. A worktree can exist without a registered Lodex environment. |
| Environment variables（環境變數） | Values supplied to a command or service; distinct from an environment registration. |

The Console uses **Environment** for the managed object and **worktree** when an
action concerns the Git directory. Adding an environment either creates a new
worktree or attaches an existing one. Removing a worktree retains the environment
record; **Unregister** (`worktree forget`) removes that registration
without deleting its files. A branch is observed context, not an environment ID.
Older material may call the physical directory a *checkout*; this is not a fourth
managed object. References to a source checkout in packaging instructions mean
the repository's source working directory.

Projects have a fixed **ID** used by CLI commands, environment registrations and
new worktree paths, plus an optional **display name**. The Console shows the name
when present and falls back to the ID for older registrations. Names may contain
spaces and Unicode, must contain 1-120 characters after trimming, and may not contain
control characters. Names need not be unique; selectors show the fixed ID when
it differs. `project rename PROJECT NAME` changes only the display name. Existing
environments, paths, repository identity and configuration sources stay the same.
`project pin PROJECT` and `project pin PROJECT --unpin` control persistent sidebar
pinning. Older records without `pinned` are unpinned. `project delete PROJECT` previews
removing a project registration; `--yes` confirms. Both stages reject projects with
any environment registration, including missing worktrees. Delete does not remove
repository files, Git worktrees, services or resource records. Remove environment
registrations deliberately before deleting the empty project. Creation, attachment
and project deletion share the registry lock to prevent orphan registrations.
No database migration is needed. Project pages show the source worktree, with the
configuration source under Details. Each worktree reads its own `.lodex/project.toml`;
editing a source file does not synchronize other environments' configuration.

Management is CLI-first and works without Codex or Ollama. History commands
retain their own configuration and database under `$LODEX_HOME/history` by default.
`LODEX_HOME` defaults to `~/.lodex`;
management.db, operation logs and service handles live there, outside worktrees.
New worktrees live under `LODEX_HOME/projects/PROJECT/BRANCH-SLUG--SHORT-ID`.
For example, branch `demo/change-title` can produce `demo-change-title--a3f19c82`.
The slug uses lowercase ASCII letters and digits, replaces runs of other characters
(including `/`) with `-`, trims edge hyphens, and is capped at 64 characters.
An empty slug uses `worktree`. The suffix is the first eight characters of the
full 16-character taskenv ID. ID or path collisions generate a fresh ID before
Git creates the worktree; existing files and retained taskenv paths are not reused.

Directory names are fixed at creation. Branch renames or switches do not move
worktrees or change taskenv IDs. Existing paths, including older ID-only directories
and attached worktrees, remain unchanged; no migration is needed. Use the returned
full ID or absolute path with `--target`, not the slug or short suffix alone.

```sh
lodex project add app /absolute/repo --config /absolute/project.toml --json
lodex project add another /absolute/another-repo --display-name "Another project" --json
lodex project rename app "App development" --json
lodex worktree create app --ref main --branch feature-one --json
lodex worktree attach app /absolute/existing-worktree --json
lodex context --target /absolute/worktree/subdirectory --json
lodex worktree list --json
lodex worktree inspect --target TASKENV_ID --json
```

`project add NAME PATH` registers the repository and ensures its worktree has
`.lodex/project.toml`:

- Existing configuration is validated and preserved, even with `--config`.
  Invalid existing content reports an error and is never replaced.
- Missing configuration is copied from `--config PATH` when specified. A missing
  or invalid explicit source reports an error instead of creating a skeleton.
- Without an explicit source, missing configuration is initialized with
  `schema_version = 1` and commented environment/secret examples. No commands,
  services, credentials or ports are inferred.

The response's `configuration` reports `method` (`existing`, `copied` or
`initialized`) and `path`; initialization also returns a `next_step` to edit the
recipe. A skeleton allows registration but needs repository-specific commands
before prepare/start can work. It does not automatically attach the worktree.
New project registrations use this worktree's TOML as the source for subsequent
worktrees, so editing the local copy is sufficient; the original `--config` file
is not a continuing dependency. Repeated registration preserves the registered
project identity/source and validates the target worktree's current recipe.
Registry conflicts and a busy lock fail before creating configuration files.
Repeated registration of the same ID and repository remains idempotent and returns
`already_registered: true`; it preserves the current display name. Use `project rename`
to edit it. Conflicts identify the existing project in the error message and
`error.details.existing_project` so the Console can link to it.

ID or absolute directory selects an environment. No session, branch, remote or
global current environment is inferred. Two clones of the same remote are distinct
projects. One worktree has one current taskenv. Main/external/detached worktrees can
be attached in place. Inspect retains records for missing/replaced paths; context
rejects them. Git common-dir and directory identities are checked before operations.
An absolute path inside a nested repository or worktree selects that worktree only
if it is registered; it never falls back to an enclosing worktree's taskenv.
The current directory is read only when a target-taking command omits `--target`.
If that directory was deleted, pass an explicit ID or absolute worktree path;
commands such as `project list` do not need a current directory.

Worktree creation acquires the registry lock before invoking Git and holds it
through registration. A busy registry returns `busy` without creating a branch or
worktree. If Git succeeds but configuration setup fails, the owned worktree remains
registered for inspection and a later `worktree attach` retry.

Each worktree owns `.lodex/project.toml`. An existing file wins, even if invalid
(invalid content reports an error and is not replaced). Create, attach and prepare
copy only a missing file from the explicit `--config` or registered source. The
source may be tracked, untracked or ignored. This configuration fallback copies
only TOML; Git checkout supplies tracked files normally. Read operations do not
supply configuration. Required scripts may be absent from an old commit.

### Updating integrations

Updating the registered source does not refresh an existing taskenv's recipe or
scripts. Apply updates explicitly, preserving local configuration and ownership
records. Use a CLI/Console build supporting the recipe's fields, and restart the
Console after updating Core. Follow the repository's preparation instructions;
running services retain their launch configuration until stopped and started again.

Keep new Lodex-specific integration scripts in `.lodex/scripts/` and supporting
files such as Compose configuration in `.lodex/`; existing project scripts can be
referenced in place. These paths are a convention, not a schema restriction. The
developer or an authorized agent creates the integration files during initial
setup, optionally guided by the project-setup Skill. Commit the TOML, scripts and
supporting files so new worktrees inherit them from their starting ref. Exclude
runtime records with narrow rules in `.lodex/.gitignore`, keeping the recipe files
trackable; keep real secrets out of tracked files. The CLI does not generate
integration scripts or copy the whole `.lodex/` directory.

## Command reference

All commands below begin with `lodex` and support `--json`. Put flags after the
command name. Replace uppercase placeholders with actual values; square brackets
indicate optional arguments and are not typed literally.

Commands marked **Target** accept `[--target TASKENV_ID_OR_ABSOLUTE_PATH]`.
Without it, Lodex resolves the registered worktree containing the current
directory. Relative target paths are not accepted. Port keys, command and service
names must be declared in `.lodex/project.toml`. Secret commands use central stored
names, without a `secret:` prefix, and need no project, worktree or `--target`.

### Projects and worktrees

| Command | Target | Purpose |
| --- | --- | --- |
| `project add NAME PATH [--config PATH] [--display-name TEXT]` | No | Register a repository; NAME is the fixed ID. Preserve its existing recipe or create/copy a missing one; does not attach a worktree. |
| `project rename PROJECT NAME` | No | Change the display name using the fixed project ID; preserve environments and worktree paths. |
| `project pin PROJECT [--unpin]` | No | Pin or unpin a project in Console navigation. |
| `project delete PROJECT [--yes]` | No | Preview or delete an empty project registration; retain all files and other records. |
| `project list` | No | List registered projects. |
| `worktree create PROJECT --ref REF --branch BRANCH [--config PATH]` | No | Create a new branch and owned worktree from a Git ref, then register it; does not run prepare. |
| `worktree attach PROJECT PATH [--config PATH]` | No | Register an existing worktree belonging to the project's local repository, including its main worktree. |
| `worktree list` | No | List registered environments and their current inspection state. |
| `worktree inspect` | Yes | Inspect configuration, worktree identity and known resource records, even when the worktree is missing. |
| `context` | Yes | Resolve and inspect an environment whose worktree is still present and matches its saved identity. |
| `worktree remove [--yes] [--force]` | Yes | Preview deletion of an owned worktree; `--yes` executes, `--force` overrides Git protection. Retain the branch and taskenv record. |
| `worktree forget [--yes]` | Yes | Preview or execute deregistration only; do not stop services or delete worktree files. |

### Repository commands, services and operations

| Command | Target | Purpose |
| --- | --- | --- |
| `prepare [--config PATH]` | Yes | Supply missing configuration if needed and run `commands.prepare` in the foreground. |
| `run NAME` | Yes | Execute the repository-defined `commands.NAME.argv` in the foreground and record its outcome. |
| `cleanup` | Yes | Run `commands.cleanup`; resource cleanup depends on the repository's recipe. |
| `service start NAME` | Yes | Start a configured process and check its configured readiness condition. |
| `service stop NAME` | Yes | Stop a managed service using its saved process identity. |
| `service list` | Yes | List saved service records and refresh their state. |
| `service inspect NAME` | Yes | Inspect one saved service record and refresh its state. |
| `service logs NAME` | Yes | Read the recent log tail; does not continuously follow output. |
| `operation list` | Yes | List recorded repository command runs for the environment. |
| `operation inspect OPERATION_ID` | No | Inspect a run's state, exit information and recorded resources. |
| `operation logs OPERATION_ID` | No | Read a recorded run's recent log tail. |

### Environment settings and secrets

| Command | Target | Purpose |
| --- | --- | --- |
| `env show` | Yes | Show resolved ordinary settings, port assignments and secret references, without secret values. |
| `env export [--output RELATIVE_PATH]` | Yes | Write resolved values, including secrets, to `.env` or a relative path inside the worktree; the parent must already exist. |
| `port set KEY VALUE` | Yes | Change a declared port assignment to an available port from 1–65535; does not restart services. |
| `secret list` | No | List all stored secret names in the management DB, never their values; works before any project is registered. |
| `secret set NAME [--stdin]` | No | Create or update a central value using hidden terminal input or a trusted pipe. |
| `secret remove NAME [--yes]` | No | Preview or delete a central value shared by every use of `secret:NAME`. |

For example, `API_TOKEN` is the environment variable name while `secret:app-token`
is its storage reference. `lodex secret set app-token` manages that value directly.
Setting or removing it affects every environment using that reference in the same
management DB. Edit ordinary values and reference mappings in each worktree's
TOML; there is no DB override layer. `env show` displays the resolved ordinary
values, allocated identifiers/ports and configured references without requiring
the secrets to be set. It does not read an existing `.env`.

## Version 1 configuration

```toml
schema_version = 1
tools = ["python3"]
[env]
DATABASE_NAME = "app_${LODEX_TASKENV_ID}"
[ports]
PORT = 0
[secrets]
API_TOKEN = "secret:app-token"
[commands.prepare]
argv = ["python3", ".lodex/scripts/prepare.py"]
scripts = [".lodex/scripts/prepare.py"]
[commands.verify]
argv = ["python3", ".lodex/scripts/verify.py"]
scripts = [".lodex/scripts/verify.py"]
[commands.cleanup]
argv = ["python3", ".lodex/scripts/cleanup.py"]
scripts = [".lodex/scripts/cleanup.py"]
[services.web]
argv = ["python3", ".lodex/scripts/web.py", "--port", "${PORT}"]
scripts = [".lodex/scripts/web.py"]
ready_port = "PORT"
ready_timeout = 10
url = "http://127.0.0.1:${PORT}"
[services.worker]
argv = ["python3", ".lodex/scripts/worker.py"]
scripts = [".lodex/scripts/worker.py", ".lodex/scripts/worker_ready.py"]
ready_argv = ["python3", ".lodex/scripts/worker_ready.py"]
ready_timeout = 120
stop_timeout = 45
```

Scripts above are examples and must exist in the target repo. Unknown fields and
unsupported versions fail validation. `argv` is a nonempty string array, executed
directly in the worktree. Use an explicit shell only when the repo requires one.
Declare repo script dependencies in `scripts`; `tools` lists required executables.

Inputs are `LODEX_TASKENV_ID`, `LODEX_PROJECT`, `LODEX_WORKTREE`, saved ports,
repo `env` values, then configured secret values.
The three user sections must have distinct uppercase names; `LODEX_` is reserved.
`${NAME}` interpolation uses values already resolved, without recursion or a
dependency graph. Ordinary values should reference the identifiers/ports. Secrets
cannot appear in argv or public URLs. Only basic OS variables (PATH, HOME, USER,
LOGNAME, LANG, LC_ALL, TMPDIR, SYSTEMROOT) are inherited. Repo scripts may source
their own explicitly managed configuration if needed.

Ports are allocated once; `0` chooses an available port, a nonzero value requests
that specific port. New callers reuse the assignment. The registry coordinates
managed taskenvs; unrelated processes may still claim a port later. Start reports
actual conflicts. `lodex port set PORT 24000 --target ID` explicitly changes an
assignment; a nonzero recipe port must agree. Stop existing services first.

```sh
lodex env show --target ID --json
lodex secret list --json
lodex secret set app-token
lodex secret remove app-token --json  # Preview only
lodex env export --target ID --output .env --json
```

Secret set uses hidden terminal input, or `--stdin` for a trusted pipe. Values are
stored **in plaintext** in the `secrets` table of `LODEX_HOME/management.db`.
There is no encryption, master key, or operating-system keychain dependency.
The management directory is restricted to 0700 and writable DB opens enforce 0600
permissions on POSIX. Trust the local user account: another process with the same
access can read the values. Treat the DB and its backups as sensitive files; keep
them out of Git, ordinary diagnostic bundles and shared folders.
Queries show references only. Secret values never enter Lodex argv or public records.
Known values are redacted from managed logs and results; arbitrary repo scripts can
still disclose values to their own files or external systems. `secret remove NAME`
previews deletion of the SQLite value shared by all uses of that reference;
`--yes` performs it. Removing a mapping from TOML does not delete the stored value.
Cleanup/worktree remove/forget never delete secrets. Deletion removes the current
entry; it does not promise forensic erasure of SQLite pages, journals or backups.

The same `secret:NAME` in one management DB shares a value across projects and
taskenvs. Use distinct names and TOML mappings for separate credentials. Editing
one worktree's mapping does not affect another worktree. A new command/service
start or export reads the current values; running processes and existing exports
do not update automatically.
Names are references, not secret values. Writable commands upgrade management
schema 1 or 2 to 3; read-only commands do not migrate. The upgrade removes obsolete
taskenv `settings` and `secret_refs` overrides, keeps stored secret values and other
records, and does not edit TOML. Ordinary values and mappings now come only from
each worktree's current TOML.
Older `keychain:` references are rejected with instructions to use `secret:NAME`
and set the value again by name.
Existing Keychain values are neither read, migrated nor deleted automatically.

Dotenv export writes a 0600 file with quoted values. It refuses Git-tracked files,
unignored secret output and handwritten/modified existing files. A generated file
can be refreshed only while its content matches Lodex's saved digest. No Git ignore
changes are implicit. An existing source `.env` is never copied.

Application configuration files are optional; their loading and synchronization
are project-defined. Lodex passes resolved `[env]`/`[secrets]` inputs to processes;
`env export` only writes those resolved inputs.

## Commands and services

```sh
lodex prepare --target ID --json
lodex run verify --target ID --json
lodex service start web --target ID --json
lodex service list --target ID --json
lodex service inspect web --target ID --json
lodex service logs web --target ID --json
lodex service stop web --target ID --json
lodex operation list --target ID --json
lodex operation inspect OPERATION_ID --json
lodex operation logs OPERATION_ID --json
lodex cleanup --target ID --json
```

One-time commands stay in the foreground and save exit status, logs and results.
They receive `LODEX_RESULT_FILE`, an optional result-file path. The JSON contract:

```json
{"resources":[{"name":"database","kind":"postgres","id":"app_123","scope":"exclusive","state":"present"}],"urls":["http://127.0.0.1:24000"]}
```

Resource scope is exclusive/shared; state is present/removed/unknown. Results are
timestamped observations, not a complete external inventory. Scripts decide order,
migrations, backups and retry behavior. Nonzero exit is failed; handled signals are
interrupted; lost callers or malformed results are unknown. No automatic retry or
recovery occurs. Logs return the last 64 KiB. Inspect after caller termination.
Handled SIGINT/SIGTERM interrupts send SIGTERM to the command's process group,
keep collecting output during a three-second grace period, then kill remaining
members before releasing the operation locks. The leader remains unreaped until
the final signal so an early parent exit cannot leave descendants behind or allow
the group ID to be reused during cleanup. SIGKILL cannot perform this cleanup.

Services use a per-service supervisor and an authenticated loopback control socket.
The supervisor owns the subprocess group; another CLI can stop it without relying
on a stored PID/port alone. CLI exit or page closure does not stop services. There
is no central daemon, automatic restart, boot startup or persistent scheduler.
If the supervisor itself disappears, its control handle is unknown; inspect/manual
recovery is required. Do not daemonize or detach inside a managed service command.
Stopping sends SIGTERM to the whole group, waits the full `stop_timeout`, then
sends SIGKILL to remaining members. Status stays `stopping`; inspection remains
available, but concurrent writes can return `busy` while another caller holds the
taskenv lock. The supervisor keeps the leader unreaped until the final signal
to prevent process-group ID reuse, including after early exit or readiness failure.
Choose enough grace for application shutdown and teardown. This setting applies
only to services; repo commands retain their fixed three-second interrupt grace.

| Service field | Default | Meaning |
| --- | --- | --- |
| `ready_port` | Unset | A name from `[ports]`; mutually exclusive with `ready_argv`. |
| `ready_argv` | Unset | A nonempty argument array for a startup probe; exit 0 means ready, other exits retry. |
| `ready_timeout` | 10 seconds | Overall readiness budget; a number greater than 0 and at most 300. |
| `stop_timeout` | 3 seconds | Grace before SIGKILL; a number greater than 0 and at most 300, saved at launch. |

`ready_port` checks TCP availability after launch; it does not prove full app
health or isolation. `ready_argv` executes directly in the service cwd/environment,
with the same interpolation and secret-in-argv protection as service argv.
Probe-only environment variables `LODEX_SERVICE_PID` and `LODEX_SERVICE_STARTED_AT`
identify the current launch; they are not TOML placeholders. Use them to reject
stale readiness records. Probes run one at a time, have no stdin, discard output
and retry with a one-second attempt limit. Their process groups are killed on
completion, timeout or service stop. Keep probes read-only and declare their
dependencies in `scripts`.

Readiness checks run only during startup. With neither check, `running` means
the process survived the initial startup interval. A failed `service start` also
waits for shutdown, so it can take `ready_timeout` plus `stop_timeout` and control
overhead. New starts read current configuration; stop uses the saved handle and
timeout even when configuration or checkout is gone.

Third-party APIs and shared dependencies are application connections; only managed
processes belong in `[services]`. A per-taskenv substitute can be a normal mock
service with an allocated port. Application isolation is project-defined;
resource reports describe shared/exclusive scope independently of service management.

The `services.NAME.external` field is no longer accepted, including `false`.
Remove a URL-only service entry and configure the connection in the application;
for a managed process, remove the field and supply `argv`. Lodex reports an error
with guidance and does not rewrite the TOML.

Previously saved `state=external` records remain visible with their original URL
and a read-only warning. They are never automatically deleted, refreshed or
converted into managed services. Start, stop and logs return `legacy_service`;
use a different service name for a new managed process. These records do not block
worktree removal, and remain stored after remove/forget. No database migration or
new external-link feature is introduced.

## Cleanup and removal

Cleanup runs the current repo command; missing scripts/configuration explain why
manual handling or restoration is necessary. To remove a Lodex-created worktree:

```sh
lodex worktree remove --target ID --json
lodex worktree remove --target ID --yes --json
```

The first command previews Git state, deletion range and known service/operation
records. Stop/resolve services first. Normal removal preserves Git refusal for
dirty or untracked content. Only explicit `--force` overrides Git protection;
ignored files are also deleted and the branch is retained. External/main worktrees
cannot be removed. Taskenv records remain inspectable after removal.

`worktree forget --target ID` previews deregistration; `--yes` removes the taskenv
registration, not services or resources. Keep operation records for evidence.
Complete cleanup before forgetting; there is no generic resource recovery system.

## CLI and skills

Management JSON successes use `{"ok":true,"result":...}`; errors use
`{"ok":false,"error":{"code":"...","message":"..."}}`. A completed repo operation
returns its result with `ok=false` and exit 1 if failed/interrupted/unknown. Usage
errors exit 2. Inspecting a failed operation succeeds as a query. Commands reject
concurrent mutations of the same taskenv; callers do not automatically retry.

```sh
lodex skill install lodex-worktree
lodex skill install lodex-services
lodex skill install lodex-project-setup
```

Omitting the name still installs/removes lodex-history. Named installation uses
the existing managed-copy workflow and supports `--dry-run`. Skills invoke CLI
commands, do not edit registry files, and report the directory/ID for caller handoff.

The bundled `.lodex/project.toml` provides Lodex's service-free prepare/verify
recipe. Example service definitions illustrate the configuration format; verify
the actual repo commands and resource isolation when connecting a project.

## Entry points and handoff

- **CLI-first:** register a repository, create a worktree or attach a worktree,
  then prepare and operate its configured services. Each create/attach response
  supplies the taskenv ID and absolute directory for subsequent commands.
- **Agent calling Lodex:** use the same CLI with `--json` and an explicit target.
  A new conversation inspects the existing ID/path; it does not implicitly create
  another environment or restart services. Skills guide the repo-specific setup.
- **Externally created worktree:** run `lodex worktree attach PROJECT /absolute/path`.
  Lodex keeps that worktree in place and does not acquire permission to delete it.

The [console](console.md) is another caller of the same core, not another owner
of the environment. Worktree inspection reports the currently observed branch
and commit (`branch: null` for detached HEAD); switching branches does not change
taskenv identity. Missing/replaced paths retain known records and cleanup guidance.

For a runnable multi-service example, see the
[self-contained fixture](../examples/multi_service/README.md). Its HTTP services,
SQLite database/queue and worker verify isolation without another project or Docker.
Application-specific provisioning, migrations, service scripts and acceptance
runners belong in that application's `.lodex/`. Lodex consumes the common recipe
and result contracts; configuration/parser tests alone do not establish isolation
for an actual application.
