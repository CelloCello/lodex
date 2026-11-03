# Using Lodex with Herdr: persistent A/B/C sessions

[Back to README](../README.md) · [Environment command reference](management.md)

Keep a manager conversation in the source repo to prepare task environments,
launch sessions B/C, collect results and verify changes. You can continue with
A or work directly in B/C and return to A; completing a turn keeps them available.
Lodex manages environments, commands and services. Herdr manages panes and agent
processes. The `lodex-herdr` skill connects these operations into a workflow.
Herdr is optional; a single agent can also use Lodex directly.

The Codex-specific policy/launcher uses current permission-profile interfaces.
Check installed versions and validate effective settings before relying on them.
Herdr TUI and herdr-core are separate runtimes; Herdr App presents core terminals.
Other agents require their own validated launch/permission contract.

## Roles and working directories

| Item | Manager | Worker |
| --- | --- | --- |
| Working directory | Source repo, with plans and the coordinating conversation | The checkout Lodex created for the task |
| Responsibilities | Prepare taskenvs, coordinate, authorize services, review and integrate | Edit own checkout, run direct tests, operate own authorized services and report |
| Lodex and Herdr | Manage lifecycle, delegate services, launch and observe agents | Control explicitly delegated services; report other environment needs |
| Git | Commit and integrate as authorized | Read status and diffs; leave Git writes to the manager |
| Suggested Codex config name | `lodex-manager` | `lodex-worker` |

Manager and worker are collaboration roles. `lodex-manager` and `lodex-worker`
are config profile names, not Lodex subcommands or background services. Each
worker is a separate agent session and does not inherit the manager's conversation.

## 1. Prepare the tools and project

Complete the [Lodex installation](../README.md#installation), install
[Herdr](https://herdr.dev/), and sign in to Codex. Check the installed versions
and supported arguments:

```sh
lodex --version
codex --version
codex --help
herdr --version
herdr agent
```

Install the Lodex skills used in this workflow, and keep Herdr's own skill:

```sh
lodex skill install lodex-herdr
lodex skill install lodex-project-setup
lodex skill install lodex-worktree
lodex skill install lodex-services
```

See [Herdr's documentation](https://herdr.dev/) for its skill installation.
Restart the agent after installation and confirm it can read these skills. If
you do not yet have a working `.lodex/project.toml`, complete the
[first website walkthrough](manual-validation.md) before delegating to multiple
agents.

The examples assume a source repo at `/absolute/path/to/demo`, registered in
Lodex as `demo`. Later examples use an existing `main` ref and a recipe with a
`verify` command; adapt these to your project:

```sh
source_repo="/absolute/path/to/demo"
lodex project add demo "$source_repo"
```

Reuse an existing registration's name and path. Commit any configuration and
scripts needed by new checkouts, and ensure the starting ref includes them;
uncommitted changes do not automatically appear in a new worktree.

## 2. Configure the manager and worker

Use the bundled templates as starting points for two files under the actual
`CODEX_HOME`. Their default destinations are:

| Template | Destination | Baseline approval policy |
| --- | --- | --- |
| [Manager](../cli/src/lodex_cli/bundled_skills/lodex-herdr/assets/lodex-manager.config.toml) | `~/.codex/lodex-manager.config.toml` | `on-request` |
| [Worker](../cli/src/lodex_cli/bundled_skills/lodex-herdr/assets/lodex-worker.config.toml) | `~/.codex/lodex-worker.config.toml` | `never` |

Compare existing files before merging the necessary fields. Preserve unrelated
settings and inspect inherited Herdr hooks. Installing the skill copies instructions and templates;
**it does not install or activate these two config files**.
For initial setup, open Codex as usual in a source-repo pane inside Herdr, then ask:

```text
$lodex-herdr

Inspect this repo and the existing Codex manager/worker configuration, then
propose a setup suitable for this project. Preserve unrelated settings, review
Herdr hooks/tools against the worker boundary, and do not replace global defaults or pin a model.
Resolve the source repo, Git common directory, LODEX_HOME and actual Herdr socket.
Show destination files, proposed changes and access scope for my confirmation
before applying them. This request is setup only: do not launch workers or
create taskenvs.
```

Replace the manager template's `/REPLACE_WITH_LODEX_HOME` and
`/REPLACE_WITH_HERDR_SOCKET_PATH` with observed absolute paths. Do not leave
placeholders or shell variables in the TOML. Use `HERDR_SOCKET_PATH` from the
intended Herdr session. When drafting outside Herdr, ask the user for that pane's
information; do not guess a socket or scan unrelated sessions.
The manager needs access to the source repo, necessary Git metadata, central
Lodex state and the Herdr socket. The Lodex root may contain other projects'
records and plaintext secrets; confirm that management scope first.

Both templates also grant write access to the shared uv package cache at
`~/.cache/uv`. Confirm `uv cache dir` in the intended command environments and
adapt that one grant if an existing override selects another path. Each checkout
keeps its own virtual environment. Ordinary uv commands then use the shared cache
without recipe changes or per-command/pane `UV_CACHE_DIR` settings. Workers leave
cache cleanup to the manager; the manager coordinates maintenance when other uv
commands are stopped. This exception permits writes to cache artifacts used by
other tasks, so choose task-specific caches if workers must not have that scope.

The manager template itself allows only the specified Herdr socket and does not
pre-allow public network destinations. Inspect inherited network rules, then
allow dependency hosts or local services as required by the project.
The worker baseline disables command network access. Tests needing local services
require a reviewed network policy; allowing localhost does not restrict access
to just that task's service.

Use the worker's checkout as its working root, without extra grants for the
source repo, central Lodex state, shared Git writes or Herdr control. Inspect and
restrict inherited MCP, plugin, app and browser capabilities as appropriate.
The command sandbox does not constrain every tool, and default temp locations
may be shared. See the [Codex setup reference](../cli/src/lodex_cli/bundled_skills/lodex-herdr/references/codex.md)
for adaptation and validation. After applying or changing configuration, use
disposable fixtures as described there to check effective permissions and tools.
Parsing the TOML or starting an agent does not verify isolation.

The manager template includes an optional automatic reviewer in its top-level
settings:

```toml
approval_policy = "on-request"
# approvals_reviewer = "auto_review"
default_permissions = "lodex-manager"
```

If desired, uncomment `approvals_reviewer` after confirmation. It changes who
reviews eligible requests, without expanding sandbox permissions or guaranteeing
approval. Keep workers on `never`; they report missing capabilities to the manager.
These fields belong before any `[table]`. See the
[OpenAI configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

`-p lodex-manager` loads `$CODEX_HOME/lodex-manager.config.toml`; its
`default_permissions` then selects a named permission profile. Do not mix this
with legacy `sandbox_mode`, `sandbox_workspace_write` or launch overrides.
Profiles layer over base configuration. Check the effective result using the
[OpenAI profile documentation](https://learn.chatgpt.com/docs/config-file/config-advanced)
and [permission documentation](https://learn.chatgpt.com/docs/permissions).

## 3. Start A in TUI and optionally add a shortcut

Open a shell pane at the source repo inside Herdr, then start the manager:

```sh
source_repo="/absolute/path/to/demo"
codex -p lodex-manager -C "$source_repo"
```

This is the TUI entry point. A core/App coordinator can also be an existing source
checkout session; see the core reference for explicit context and parent selection.
**You start A; A reads the skill and starts B/C**. A skill cannot reconfigure an already-running manager.
After changing a profile, restart or resume the session and check its effective
working directory and permissions; editing a file does not update an existing
process.

For a shortcut, add the following block to the Herdr config. The Linux/macOS
default is `~/.config/herdr/config.toml`; for a custom path, use the location
shown by `herdr --help`. Check whether `prefix+m` is already bound; reuse or
adjust an existing entry instead of adding a duplicate.

```toml
[[keys.command]]
key = "prefix+m"
type = "pane"
command = 'exec codex -p lodex-manager -C "${HERDR_ACTIVE_PANE_CWD:?Select a repository pane first}"'
description = "Start Lodex manager (Codex)"
```

Run `herdr config check`, then choose **Reload config** in Herdr's global menu.
Select a source-repo pane and press the configured prefix followed by `m`;
the default is **Ctrl+B → m**. This opens a temporary, zoomed manager pane at
the selected pane's directory, and closes it when Codex exits. Paths containing
spaces are passed intact; a missing working directory prevents launch.

This shortcut leaves a plain `codex` launch unchanged and keeps workers on their
own profile. **Reload config reloads Herdr configuration; it does not reload
profiles in existing Codex sessions.** The shell syntax above targets Linux/macOS.
See [Herdr configuration](https://herdr.dev/docs/configuration/) for platform
differences and key conflicts.

## 4. Dispatch once and keep A/B/C interactive

Give session A the tasks and select TUI or core/App. For example:

```text
$lodex-herdr

Project demo, starting from main: assign the navigation fix to B and the API
validation fix to C, in different Lodex taskenvs. Prepare each environment, give
each agent scoped control of its own web service, and launch interactive Codex
sessions through the selected Herdr runtime. Keep A available for coordination
and B/C available after each turn. I may give B direct follow-up instructions.
Report current progress and tests; retain environments until explicit cleanup.
```

A creates each taskenv with `worktree create` and keeps its returned ID/path
before attempting prepare. `lodex prepare --target ID --json` safely exports the
optional project `[taskenv] env_file = ".env"` before running its recipe. Without
that declaration the recipe may generate its own application settings. Missing
inputs/scripts or failed preparation stop dispatch; repair and retry the same ID.
The successful result's `handoff` carries context, not permanent readiness or
authority. Project secrets may share values while DB/queue/ports/data remain
taskenv-specific. See [configuration delivery](management.md#version-1-configuration).

For each taskenv with worker-controlled services, A starts a foreground
[delegation controller](service-delegation.md) in a separate trusted terminal.
It authorizes and records; service code runs under B/C's execution permissions.
No services means no controller is needed. A can be idle or handle other work
while B/C independently start, inspect, read logs, stop and restart their services.

After successful prepare and grant creation, draft the worker settings:

```sh
lodex worktree worker-config --target TASKENV_ID \
  --prepare-operation PREPARE_OPERATION_ID --profile lodex-worker \
  --uv-cache /observed/uv/cache --delegation GRANT_ID \
  --deny-socket /observed/runtime/control.sock --json
```

Omit `--delegation` when not needed. Repeat `--deny-socket` for control endpoints;
explicit `--allow-host HOST` adds reviewed application networking. Review the
returned filesystem/socket/tool scope. This command writes a protected policy,
not a global profile, and does not launch an agent. It uses a unique permission
profile for each launch and fails on changed recipes or inspected legacy sandbox
settings. The existing worker config is a baseline; it alone does not deliver
delegated socket permissions or central/peer read denials.

Use the returned short `launcher_argv`, policy path and focused task file through
the selected adapter:

| Runtime | Launch and observation |
| --- | --- |
| TUI | [TUI reference](../cli/src/lodex_cli/bundled_skills/lodex-herdr/references/tui.md): actual Herdr caller, exact cwd, no-focus split, short pane command, agent readiness/read/wait. |
| core | [Core reference](../cli/src/lodex_cli/bundled_skills/lodex-herdr/references/core.md): explicit local context, interactive `hc run --bg`, parent policy, full terminal IDs, event waits. |
| App | The same core terminals; show/attach to B/C through the App UI. Opening a window/tab is separate from creating a taskenv. |

For an explicitly requested App view, an existing parentless core terminal may
need `hc label TERMINAL herdr.space=OBSERVED_SPACE_ID` before App creates its tab.
Inspect that tab and select it with `herdr-app do tab.select --id OBSERVED_TAB_ID`
in the intended App home/core context. `agent.focus` alone may only select the
sidebar entry. Confirm the visible cwd/session before typing; see the core
reference for temporary display and attachment details.

The launcher passes the first task through native agent argv, preserves
interactive follow-up, and holds a per-taskenv writer lock. It does not implement
task scheduling or share conversations. Observe actual task receipt, cwd,
permissions, tools and native session UUID. Creation/admission/readiness output
cannot replace those checks. Do not blindly relaunch or resend after a timeout.
Known local guard records live under `LODEX_HOME/worker-sessions`; they are
management observations, not task-progress databases.

When the user works directly in B/C, A refreshes their latest state/summary before
following up. A settled turn is neither task acceptance nor permission to end the
session, revoke the grant or remove the taskenv. Workers do not need runtime API
access to report; A observes their terminal output/status.

## 5. Renew, verify and explicitly finish

Recipe changes require review/new grants; ordinary code edits can stop/start
under the existing grant. A new secret value affects new starts/exports, not
already running processes or old generated files.

For grant replacement, coordinate a pause and save the native session UUID and
latest task state. Exit/confirm the old agent, inspect existing services, revoke
the old grant and create the new controller. Generate new route/permission
settings and resume the same taskenv with the new policy and `--resume UUID`.
Confirm effective settings and service operations again, update A's actual runtime
mapping, and leave C unchanged. Replacing only a credential cannot update an old
sandbox. Unknown exits block a second writer rather than triggering a blind
retry. See [lifecycle and recovery](../cli/src/lodex_cli/bundled_skills/lodex-herdr/references/lifecycle.md).

Before review/integration, agree that the worker has stopped editing. Inspect
tracked/untracked changes and direct test results. `lodex run verify` executes
repo code in its caller's permissions; use an appropriately restricted runner
when that code must remain isolated. Commit/integration/removal still require the
corresponding user authorization.

For explicit teardown, inspect the current cleanup script and project ordering
requirements, then run it in B/C or in the recorded restricted runner:

```sh
lodex cleanup --target TASKENV_ID --worker-policy /absolute/worker-policies/ID.json --json
```

The manager collects records/results while the sandbox executes the repository
command. Plain `lodex cleanup` continues to use caller permissions; do not use it
as an administrative retry for worker-modified code. The restricted path works
after the agent exits and opens only its operation's result file beneath central
state. It does not grant arbitrary command RPC access through delegation.
Project secret references must match the prepared handoff before the manager
resolves them; cleanup edits cannot silently expand access to central secrets.

A failed or uncertain cleanup preserves the environment and handles. After repo
cleanup, service stop and terminal recording/ACK succeed in the project's required
order, revoke/end the controller and perform separately authorized worktree removal
with its preview/Git protections. Keep checkout-only environments without a
permanent controller. Closing a pane/tab ends its program; closing an App window
does not end core terminals. No automatic machine-reboot/session recovery is
promised.

## Common issues

| Symptom | Check and response |
| --- | --- |
| Manager still fails on `~/.lodex` or the Herdr socket | Confirm that this session actually loaded `lodex-manager`, rather than merely having the file present; check actual paths and inherited settings. |
| Installing the skill did not change manager permissions | Skills provide instructions after startup. Select the profile at launch, restart or resume, and check the effective setup. |
| Worker needs extra environment capabilities | Have the manager handle dependencies and confirmed permission changes; do not retry with the manager profile or disable sandboxing. |
| Removal preview needs central-state access | Without `--yes`, no worktree is deleted, but the preview may still lock or write management state; run it as the manager. |
| Pane opens but work happens in the wrong directory | Check pane `--cwd`, Codex `-C` and the Lodex result path together; an open pane does not establish taskenv readiness. |

For further interface and configuration details, see the
[Herdr CLI](https://herdr.dev/docs/cli-reference/),
[integration skill](../cli/src/lodex_cli/bundled_skills/lodex-herdr/SKILL.md) and
[Codex setup reference](../cli/src/lodex_cli/bundled_skills/lodex-herdr/references/codex.md).
