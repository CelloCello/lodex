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
New worktrees live under `WORKSPACE_ROOT/PROJECT/BRANCH-SLUG--SHORT-ID`.
The default workspace root is the sibling `LODEX_HOME` plus `-workspaces`:
`~/.lodex-workspaces` for the default management root. Override it with
`LODEX_WORKSPACE_ROOT`, or set `workspace_root = "/absolute/path"` in
`LODEX_HOME/management.toml`. The environment override takes precedence.
Relative paths and overlaps with management state are rejected. Use the same
management configuration for CLI and Console; the shell override applies only
to the process receiving it.

The workspace root must also stay outside registered task checkouts and Git
metadata, and must not equal a registered project's source checkout. A
project-local subdirectory is supported when the source is not itself a taskenv.
Task checkouts must not contain a saved workspace root or enter
the reserved `.r` / `delegation-sockets` namespaces. General management still
supports nested checkout registration/target resolution, but overlapping
checkouts cannot receive isolated worker policies. When registering an overlapping
checkout, Lodex holds the existing task and writer locks through registration. A live
worker, an unconfirmed exit, an operation in progress or a service awaiting shutdown
or ACK blocks the change. Parallel sibling checkouts keep independent locks.
Creation, attachment/rebinding and new worker policy admission enforce these
rules, including records created by older releases. No existing policy file or
running task is rewritten by validation.

Each new environment records its resolved `workspace_root`. Changing the setting
affects new registrations only. Existing checkouts, service handles, prepared
handoffs, policies and sessions stay at their saved paths, including legacy
environments under `~/.lodex/projects`. No running task is migrated or restarted.
New worker temp/result files and delegated service observations use
`WORKSPACE_ROOT/.r/TASKENV_ID/`; delegation endpoints use
`WORKSPACE_ROOT/delegation-sockets/`. Short runtime paths accommodate Unix socket
limits independently of readable project/branch names. An excessively long root
fails with `socket_path_long`; select a shorter location for new environments.
Management DBs, secrets, policies, locks, session records, operation logs and
authoritative service control handles remain under `LODEX_HOME`.

Worker policies protect management state from reads and writes. Other workspaces
are readable but not writable, including tasks created after a worker starts.
Only the assigned checkout, current worker/delegation runtimes and explicitly
reviewed shared cache are writable. This is write isolation for cooperating tasks
of one OS user, not confidentiality between projects or a VM boundary. Application
ports, databases and external services still follow the project's resource contract.

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
Removal and deregistration hold the worker-session lock and reject active or
unconfirmed workers, active delegations, running operations, live services and
pending terminal ACKs. Finish scoped cleanup, stop services, exit the worker and
revoke its delegation first. For a delegated service that exits on its own,
use `lodex service stop` for that task and service to record the terminal result
and ACK its supervisor. Removal, deregistration and rebinding require the saved ACK
for the current launch as well as completion of older pending ACKs.
Retained runtime observations and central history are
not deleted with the checkout; `forget` remains deregistration, not runtime pruning.

For an unconfirmed worker exit, first preview its saved launch record:

```sh
lodex worktree reconcile-worker --target TASKENV_ID --json
```

Inspect that record's actual runtime and verify the old agent and unmanaged
writers have exited. Then explicitly confirm that same launch record (the ID
is distinct from the native conversation UUID):

```sh
lodex worktree reconcile-worker --target TASKENV_ID --record-id LAUNCH_RECORD_ID \
  --evidence "Observed exit in the saved terminal; verified no old writer remains" --yes --json
```

An active writer lock, stale record ID or missing evidence rejects confirmation.
New launch guards pass the lock descriptor to the agent, so an agent retaining
that descriptor still blocks admission after guard termination. Older agents
and programs that close inherited descriptors require the same manual runtime
verification; a free lock/PID lookup alone is never exit proof. This command does
not kill processes or stop managed services. It saves the original record and
evidence centrally as a `worker-reconciliation` receipt, marks the session
`reconciled`, and preserves its native UUID and unknown exit code. Receipts remain
after later launches or deregistration. Resume still needs the same native UUID
(or verified native storage for the first binding); confirmation does not allow a
fresh conversation or remove service/operation/ACK teardown checks. Never delete
or hand-edit the guard record to bypass admission.

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
be attached in place. Environments register a directory location, not a permanent
filesystem object. Before execution, Lodex checks the canonical worktree path,
Git common directory, worktree Git directory and main-worktree status. Linked
worktrees also require Git's worktree listing and a matching Git-directory
backlink. Main checkouts support `--separate-git-dir`; Git's worktree list may name
the metadata directory instead of the checkout in that layout. Remote URLs,
branches, device numbers and inodes do not
define this association. Old device/inode fields are ignored without rewriting
existing registrations. A structurally identical checkout at the same location
continues using the registration, even if its physical directories were replaced.
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

### Unavailable directories and rebinding

Inspection and listing retain environment, service, operation and resource records
when directories become unavailable. `missing` means the registered path is absent;
`identity_changed` means its Git association differs or it is no longer a Git
worktree; `unavailable` means Git/filesystem access cannot currently be verified.
Inspection includes an `identity` explanation and observed association when known.
Execution rejects these states. Saved service handles still support manager-side
inspection, logs and stop independently of the checkout; they do not authorize
running a replacement checkout's cleanup recipe against old resources.

Restore a usable worktree at the registered path, then explicitly preview and
confirm its new association with the same project's Git common directory:

```sh
lodex worktree attach app /absolute/registered/path --rebind --json
lodex worktree attach app /absolute/registered/path --rebind --yes --json
```

Preview does not copy configuration or update the registration. Confirmation keeps
the taskenv ID, ports and history, drops worktree deletion ownership, increments
the binding revision and requires a successful `prepare` before further commands
or service starts. Failed prepare leaves that requirement in place. Rebind and
worker launch share the worker-session lock; launch validates the policy binding
inside that lock. Active workers, unconfirmed worker exits, service delegations,
nonterminal/unknown services, executing operations and pending supervisor
acknowledgements must be resolved first. Existing resource records remain historical
observations, not proof that a resource is still present or owned by the new checkout.
Old preparation handoffs and worker policies cannot authorize the new binding;
prepare and generate a new worker policy before dispatching a worker. Legacy worker
policies using device/inode identities must also be regenerated once.

An operation with no active execution lock can retain an `unknown` outcome (for
example, the command exited but wrote an invalid result). Rebind preview lists
these under `unresolved_operations` and `required_acknowledgements`. Inspect each
operation and its logs, verify its processes have stopped and handle any remaining
resources, then explicitly acknowledge each ID when confirming:

```sh
lodex worktree attach app /absolute/registered/path --rebind --yes \
  --acknowledge-operation OPERATION_ID --json
```

Repeat `--acknowledge-operation` for multiple IDs. This never overrides an active
operation lock, service or worker. Confirmation records acknowledgement time and
binding revision in the environment's `rebind_acknowledgements`; operation history
and resource outcomes stay unchanged. Previously acknowledged outcomes do not
block subsequent rebinds. The Console action API accepts the same IDs in
`acknowledge_operations`.

Rebinding neither creates a new environment nor transfers it between projects or
directory locations. A checkout belonging to another Git common directory must be
registered under its appropriate project. Ordinary attach remains idempotent for
an unchanged association and never silently accepts a changed one.

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

Direct repository commands (`prepare`, `run`, and ordinary `cleanup`) retain the
caller's active Codex network-proxy settings so dependency tools use the same
allowed destinations as that caller. This transport is execution-local: it is
not exported to dotenv files or saved in task handoffs. Other caller credentials
remain excluded. Controller service payloads and restricted-cleanup sandbox
launches do not inherit the manager's proxy; those are separate execution
boundaries. This behavior does not grant network destinations or local sockets.

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
| `worktree attach PROJECT PATH [--config PATH] [--rebind [--yes]] [--acknowledge-operation ID]` | No | Register an existing worktree, or explicitly preview/confirm rebinding at its registered path; confirmed rebind keeps the ID and history, drops deletion ownership and requires prepare. Repeat the acknowledgement flag for stopped operations with unknown outcomes. |
| `worktree list` | No | List registered environments and their current inspection state. |
| `worktree inspect` | Yes | Inspect configuration, worktree identity and known resource records, even when the worktree is missing. |
| `worktree worker-config --prepare-operation ID --profile NAME --uv-cache PATH [--delegation ID] [--allow-host HOST] [--deny-socket PATH] [--deny-path PATH] [--trust-checkout]` | Yes | Draft protected per-launch Codex settings for a successful prepare; no agent launch or global profile installation. Checkout trust is explicit and invocation-only. |
| `context` | Yes | Resolve and inspect an environment whose worktree is still present and matches its saved identity. |
| `worktree remove [--yes] [--force]` | Yes | Preview deletion of an owned worktree; `--yes` executes, `--force` overrides Git protection. Retain the branch and taskenv record. |
| `worktree forget [--yes]` | Yes | Preview or execute deregistration only; do not stop services or delete worktree files. |

### Repository commands, services and operations

| Command | Target | Purpose |
| --- | --- | --- |
| `prepare [--config PATH]` | Yes | Supply missing configuration, export the declared `taskenv.env_file`, then run `commands.prepare`; successful results include a handoff snapshot. |
| `run NAME` | Yes | Execute the repository-defined `commands.NAME.argv` in the foreground and record its outcome. |
| `cleanup [--worker-policy PATH]` | Yes | Run `commands.cleanup` in caller permissions, or use a protected task-bound policy for restricted execution and management-side result collection. |
| `service start NAME` | Yes | Start a configured process and check its configured readiness condition. |
| `service stop NAME` | Yes | Stop a managed service using its saved process identity. |
| `service list` | Yes | List saved service records and refresh their state. |
| `service inspect NAME` | Yes | Inspect one saved service record and refresh its state. |
| `service logs NAME` | Yes | Read the recent log tail; does not continuously follow output. |
| `service delegate --service NAME` | Yes | Serve a foreground delegation for explicitly selected services in one taskenv. |
| `service revoke DELEGATION_ID` | No | Revoke worker service control; keep services available for manager takeover. |
| `service retry-acks NAME` | Yes | Manager: retry retained terminal ACKs for this service without stopping its current launch. |
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

To deliver a dotenv file each time an environment is prepared, declare it once:

```toml
[taskenv]
env_file = ".env"
```

`prepare` validates the command and inputs, then exports this file **before**
executing the recipe, so preparation may load it. Its parent directory must
already exist; the normal export checks still reject tracked, unignored secret,
handwritten or modified outputs. A failure preserves the taskenv for inspection;
retry with the same ID after fixing it. Preparation can have repository-defined
side effects and is not guaranteed to execute only once. Without `env_file`,
no file is exported automatically; the recipe may produce its own application
settings. This optional field requires a Lodex version supporting it.

To share live planning files, add the top-level `readonly_dirs = ["_plans"]`
before any TOML table. The default is an empty list. Create the directory in
the registered source checkout first. It may be a symlink to a dedicated
directory. The effective list is the intersection of the task recipe and the
current source declaration. Removing a name at either end withdraws the share.
During prepare Lodex creates same-name links to the resolved source directories
and records their destinations in the handoff. A conflicting file or directory
is preserved. Worker launch and resume check those links and the source opt-in
and apply read access to the actual destinations. Edits to the originals are
visible immediately. Git worktree removal discards the links with the checkout.
For a private untracked plan, `/_plans` in Git's local `info/exclude` covers
both the source directory and the worktree symlink.

Use dedicated data directories outside management state, Git metadata and task
workspaces. A manager running a recipe with ordinary host permissions retains
its normal access. Prepare checks all destinations, records the identity of
each symlink it creates, and rolls back a failed link update. On re-prepare,
it can retire or replace those links. Existing links without ownership records
(including older installations) and user replacements remain user-owned.
Stop the task worker before changing its links. Relaunch to apply new settings.

Restricted cleanup uses the saved filesystem permissions as its ceiling. Under
the task lock it denies withdrawn destinations, caps current shares at read,
and retains previous denials. It can retire a task after a source symlink moves
or a share is withdrawn, without preparing it again. A cleanup recipe that
actually needs the withdrawn data will encounter the sandbox denial.

A successful prepare result contains `handoff`: the taskenv ID/path, project,
creation base commit (null for older/attached worktrees), checkout commit at
preparation, configuration and delivered-file paths, configured service names,
secret references and prepare operation ID. It contains no resolved settings or
secret values. It is a snapshot, not a permanent readiness flag or authorization:
the coordinating skill adds the task, actual runtime identity, selected agent
settings and service grant before dispatch. Failed runs have no handoff. Creating
a worktree alone still does not prepare or launch anything. A new `prepare` or
explicit `env export` refreshes a managed file; existing files and running services
do not update when a shared secret changes.

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
| `allow_local_binding` | Inferred from `ready_port` when omitted | Boolean sandbox capability for delegated workers. Set `true` for a listening service using `ready_argv`; explicit `false` disables the inference. |
| `ready_timeout` | 10 seconds | Overall readiness budget; a number greater than 0 and at most 300. |
| `stop_timeout` | 3 seconds | Grace before SIGKILL; a number greater than 0 and at most 300, saved at launch. |

`ready_port` checks TCP availability after launch; it does not prove full app
health or isolation. `ready_argv` executes directly in the service cwd/environment,
with the same interpolation and secret-in-argv protection as service argv.
Local binding is reviewed in the prepare/delegation snapshot independently of
readiness. It applies only when that service is selected in the grant, affects
newly issued worker policies, and is not a per-port firewall. Existing recipes
and their digests are unchanged when the field is omitted.
Probe-only environment variables `LODEX_SERVICE_PID` and `LODEX_SERVICE_STARTED_AT`
identify the current launch; they are not TOML placeholders. Use them to reject
stale readiness records. Probes run one at a time, have no stdin, discard output
and retry with a one-second attempt limit. Their process groups are killed on
completion, timeout or service stop. Keep probes read-only and declare their
dependencies in `scripts`.

Readiness checks run only during startup. With neither check, `running` means
the process survived the initial startup interval. A failed `service start` also
waits for shutdown, so it can take `ready_timeout` plus `stop_timeout` and control
overhead. Manager starts read current configuration; manager stop uses the saved
handle and timeout even when configuration or checkout is gone.

Workers can receive [taskenv-scoped service delegation](service-delegation.md)
without management DB access. The manager authorizes named services; workers
execute them in their own sandbox. Delegation does not change agent permissions.
Delegated operations require the original checkout identity; recipe changes need
a new grant. Terminal results are collected through the saved control handle and
recorded before acknowledging supervisor exit. See the delegation guide for
read-only queries and recovery limits. Pending ACKs survive restarts with warnings;
managers can explicitly retry them with `service retry-acks NAME`.

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
