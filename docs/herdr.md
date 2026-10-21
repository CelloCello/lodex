# Using Lodex with Herdr: manager and workers

[Back to README](../README.md) · [Environment command reference](management.md)

Keep a manager conversation in the source repo to prepare task environments,
launch workers, collect results and verify changes. You work mainly with the
manager; workers carry out their assignments in separate checkouts.
Lodex manages environments, commands and services. Herdr manages panes and agent
processes. The `lodex-herdr` skill connects these operations into a workflow.
Herdr is optional; a single agent can also use Lodex directly.

The examples use Codex and were checked against Codex CLI `0.162.1` and Herdr
`0.9.5`. Other coding agents can use the same division of responsibilities, with
their own launch arguments and permission settings.

## Roles and working directories

| Item | Manager | Worker |
| --- | --- | --- |
| Working directory | Source repo, with plans and the coordinating conversation | The checkout Lodex created for the task |
| Responsibilities | Split work, prepare environments, manage services, delegate, verify and integrate | Edit assigned files, run agreed direct tests and report results |
| Lodex and Herdr | Manage environment lifecycle; launch and observe agents | Report environment or permission needs to the manager |
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
settings and Herdr hooks. Installing the skill copies instructions and templates;
**it does not install or activate these two config files**.
For initial setup, open Codex as usual in a source-repo pane inside Herdr, then ask:

```text
$lodex-herdr

Inspect this repo and the existing Codex manager/worker configuration, then
propose a setup suitable for this project. Preserve existing settings and Herdr
hooks; do not replace the entire global config or pin a model.
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

## 3. Start the manager and add a Herdr shortcut

Open a shell pane at the source repo inside Herdr, then start the manager:

```sh
source_repo="/absolute/path/to/demo"
codex -p lodex-manager -C "$source_repo"
```

These are two separate launches: **you start the manager; the manager reads the
skill and starts workers**. A skill cannot reconfigure an already-running manager.
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

## 4. Delegate work and launch a worker

Give the newly started manager a task, for example:

```text
$lodex-herdr

Act as the manager for a mobile navigation wrapping fix in project demo.
Start from main, use a separate Lodex taskenv and branch, and follow this repo's
rules and plans. Inspect configuration and dependencies, prepare the environment,
then launch Codex through Herdr using lodex-worker.
The worker edits only this task's checkout and runs the agreed direct tests;
handle environment management and Git writes yourself.
Acceptance: no navigation overlap at 390px, desktop behavior remains correct,
and project verify passes. Review the diff and test results, then report back.
Keep the taskenv until I confirm integration and removal.
```

The manager follows the [lodex-herdr skill](../cli/src/lodex_cli/bundled_skills/lodex-herdr/SKILL.md)
through the steps below. Live Herdr session operations require a Herdr pane;
check `test "${HERDR_ENV:-}" = 1` first. Configuration drafting can continue
outside Herdr, but current-session control cannot.

### Create and prepare the checkout

Check for a suitable existing taskenv first. When a new one is needed, create
it through Lodex:

```sh
lodex worktree create demo --ref main --branch feature/mobile-navigation --json
```

Record the taskenv ID and absolute path from `result.id` and `result.path`.
The variables `taskenv_id`, `taskenv_path`, `pane_id` and `task_prompt` below must
be filled from observed results and the assignment; these snippets are not a
complete script to paste unchanged.
Creating a worktree does not run preparation commands. Read that checkout's
recipe, then run necessary `prepare` commands, install dependencies and start
services as the manager. Skip steps that are undefined or unnecessary.
Workers have no command network access by default, so prepare dependencies
before dispatch.

Use task-specific ports, temp/output locations and test data, with the shared uv
cache exception configured above. Different checkouts or ports do not isolate
databases, queues or external services. See
[environment configuration](management.md#version-1-configuration).

### Open a pane and explicitly select the worker configuration

Inspect the layout and choose a suitable right or down split. For example:

```sh
herdr pane split --current --direction right --cwd "$taskenv_path" --no-focus
```

Take `pane_id` from `result.pane.pane_id` and confirm it is an idle shell pane.
Choose an unused agent name, such as `demo-nav`, then start the worker:

```sh
agent_name="demo-nav"
herdr agent start "$agent_name" --kind codex --pane "$pane_id" -- \
  -p lodex-worker -C "$taskenv_path"
```

Do not create another checkout with Codex `--worktree` or Herdr worktree commands.
After launch, confirm the worker's effective cwd, configuration and available
tools before sending work.

### Track results and handle blockers

Turn the manager's assignment into a worker-specific prompt. Do not forward the
earlier manager orchestration prompt verbatim. For example, replace the angle
brackets below with actual values and put the complete text in `task_prompt`:

```text
You are the worker for this task.
Taskenv: <actual ID>; working directory: <actual absolute path>.
Task: fix mobile navigation wrapping; edit only related files in this checkout.
References: <applicable rules, plan paths or a focused context excerpt>.
Acceptance: no navigation overlap at 390px; desktop behavior remains correct.
Direct tests: <specific commands and checks confirmed to work in this environment>.
Report missing dependencies, services or permissions with the operation and error
to the manager. Leave Lodex, Herdr and Git writes to the manager.
When finished, stop editing and report changed files, a diff summary, test
commands and results, and unresolved issues.
```

Workers run the project's direct tests; the manager uses `lodex run verify`
to record verification. Send the assignment through agent prompt with a bounded
wait:

```sh
herdr agent prompt "$agent_name" "$task_prompt" --wait --timeout 60000
herdr agent get "$agent_name"
herdr agent read "$agent_name" --lines 60
```

A timeout does not mean delivery failed. Check status and output before following
up to avoid duplicate assignments. `idle` or `done` does not establish acceptance;
review the output and test results.
Workers report missing capabilities to the manager. Arrange authorized
dependencies or configuration corrections; do not repeatedly send the same failing
instruction or answer approval/question dialogs on the user's behalf without
authorization.

For parallel work, use a distinct taskenv, branch, pane and agent name for each
task, and keep their mapping in the manager's context. Sequence dependent work;
do not default to multiple workers writing the same checkout.

## 5. Verify, integrate and finish

Workers return changed files, diffs, test results and remaining issues. Confirm
the worker has stopped editing before the manager reviews and verifies the
changes, so the output stays stable during verification:

```sh
git -C "$taskenv_path" status --short
git -C "$taskenv_path" diff
```

Inspect new, untracked files as well as tracked diffs. `lodex run verify` writes
central state and executes checkout commands with **the manager's execution
permissions**, not the worker's sandbox. Inspect tests and scripts first; use a
separately restricted runner when arbitrary test code needs isolation.

After inspection, if the recipe defines `verify`, record the run through Lodex:

```sh
lodex run verify --target "$taskenv_id" --json
```

Within the authorized integration scope, the manager commits, reviews or
integrates the branch. Save the results before removing the environment;
retaining a Git branch does not retain uncommitted changes. Keep the taskenv and
services when further review is needed.

When the environment is no longer needed, end the worker normally, stop that
taskenv's services, run any required cleanup defined in the recipe, then preview
removal. For a project with a `web` service and `cleanup` command:

```sh
lodex service stop web --target "$taskenv_id" --json
lodex cleanup --target "$taskenv_id" --json
lodex worktree remove --target "$taskenv_id" --json
```

Review the preview's path, Git status and services. Separately check ignored
files, which are not listed in the preview:

```sh
git -C "$taskenv_path" status --short --ignored
```

Once results and any files to keep are saved, confirm removal:

```sh
lodex worktree remove --target "$taskenv_id" --yes --json
```

Do not automatically add `--force` when removal is blocked. Lodex retains the
branch and evidence records; use `worktree forget` separately only when that
registration is no longer needed. Closing a Herdr pane and removing a Lodex
taskenv are separate operations. Closing the pane neither removes the environment
nor stops services managed by Lodex.

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
