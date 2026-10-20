---
name: lodex-herdr
description: Set up or coordinate coding agents in Lodex task environments through Herdr, with explicit manager and worker permissions. Use for the combined Lodex and Herdr workflow, including parallel tasks; not for standalone history search or ordinary worktree management.
---

# Lodex + Herdr

Keep the coordinating conversation in the source checkout. Lodex owns taskenv
creation, preparation, services, operation records and removal. Herdr owns panes
and agent processes. Each worker edits one taskenv; the manager keeps plans,
delegates work and collects results. This skill supplies instructions, not a
background scheduler or an additional sandbox.

## Setup and permissions

Use the agent kind the user selected; do not silently substitute Codex. Inspect
the installed agent's help and Herdr's supported kinds before choosing launch
arguments. For a Codex manager or worker, read [Codex setup](references/codex.md)
and adapt its linked templates. Other agents need their own documented workspace,
permission and approval settings; Codex flags and templates do not apply to them.
If those controls cannot express the intended boundary, explain the gap before
launching work rather than claiming equivalent isolation.

Check existing setup first. When profiles are missing or unsuitable, present the
concrete destinations, proposed content/diff and access scope, then obtain user
confirmation before creating or changing agent configuration. Reuse confirmation
already given for that exact configuration; approval to install this skill alone
does not approve changes to agent permissions. Preserve unrelated settings. Do not
overwrite the upstream Herdr skill or change global defaults to make a task run.

The intended division is:

| Capability | Manager | Worker |
| --- | --- | --- |
| Source checkout and plans | Coordinate and maintain authorized notes | Read references |
| Taskenv files | Prepare and inspect | Write only its assigned checkout |
| Lodex state and lifecycle | Create, prepare, run, inspect, stop, clean up | Report needs to manager |
| Herdr control | Launch and observe agents | No session-control access |
| Shared Git metadata | Perform authorized Git writes | Read status/diffs |

Prepare dependencies and task-specific ports, data stores, temp/cache locations
before dispatch. Read each checkout's recipe and scripts: different directories
or ports alone do not isolate databases, queues, shared caches or external
services. A permission profile does not automatically constrain MCP tools,
browser/computer control, or other execution channels. Check the worker's actual
available tools as part of setup.

## Dispatch from the manager

For live Herdr operations, first check `test "${HERDR_ENV:-}" = 1`. If false, stop
session control and explain how to start the manager in a Herdr pane; setup advice
and configuration drafting can continue outside Herdr. Read the installed Herdr
skill when available and use `herdr --help` and `herdr agent` for current syntax.
If the skill is absent, request its setup before live orchestration; do not install
it implicitly or guess how to answer an agent's interactive UI.

1. Resolve the source repo, Lodex project, task scope, agent kind and launch
   configuration. Reuse established choices. Ask about unresolved task boundaries
   or shared-resource behavior before dependent work. Use `lodex context --target
   /absolute/path --json` and inspect explicit IDs; do not infer identity from a
   branch or pane title. Use `lodex-project-setup` for missing project recipes.
2. Reuse a suitable existing taskenv, or create the requested one through Lodex.
   Use `lodex-worktree` or the installed CLI help. Keep the returned taskenv ID and
   absolute checkout path. Do not create a second worktree through Herdr or the
   coding agent. Prepare required scripts/dependencies and services through Lodex;
   an existing taskenv or a copied recipe does not prove they are ready.
3. Inspect Herdr layout, then open a pane with that exact checkout as its `--cwd`,
   preserving user focus. Use the returned pane ID. Reconcile existing agents
   before retrying a partially completed launch; never launch two writers into
   the same taskenv by default.
4. Start the requested agent in that pane with the selected worker configuration
   and explicit working directory. Native agent arguments go after Herdr's `--`.
   For Codex, the default names from the setup reference give this command:

   ```bash
   herdr agent start "$agent_name" --kind codex --pane "$pane_id" -- \
     -p "$worker_profile" -C "$taskenv_path"
   ```

   These shell variables represent observed values, not literal placeholders to
   send. `worker_profile` is the approved config profile name (normally
   `lodex-worker`), never the manager profile. Missing/invalid settings are a setup
   failure: do not omit the profile, add broad writable roots, or disable sandboxing
   as a retry. A successful Herdr launch proves readiness, not effective permissions.
5. Confirm the worker's cwd and active configuration before productive dispatch.
   Include in its prompt the taskenv ID/path, requested change, acceptance criteria,
   source-plan paths or a focused context excerpt, direct test commands and expected
   return information. Source notes remain references unless writing is authorized.
   Workers do not inherit the manager's conversation; give them the needed context.
   State that Lodex lifecycle, Herdr control, Git writes and unavailable resources
   go back to the manager. The worker should report a denied operation with its
   error, not try another execution channel to get around the boundary.

For parallel tasks, repeat with distinct taskenvs, branches, pane IDs and live
agent names. Record their mapping in the coordinating conversation or the repo's
existing task record. Separate native agent sessions implement the work; the
manager remains the user's single coordination conversation.

## Observe and finish

Send work with Herdr's agent prompt interface and use bounded waits. Inspect
`agent get`/`agent read` on timeout or blocked state before retrying; a timeout
does not mean the prompt was never delivered. Perform authorized status reads
using existing permissions. A skill's blocked-UI rule is not a reason to request
escalation for every read. If access is actually denied, report the operation and
error; do not assume that a read needs to run outside the sandbox.

Do not answer a worker approval/question dialog without the user's authorization
for that answer. Treat a worker permission failure as a manager task: arrange an
authorized dependency or correct a confirmed setup, then continue with the same
taskenv. Do not repeatedly send the same failing instruction.

Workers run the agreed direct tests and return changed files, diff, results and
remaining blockers. Confirm the worker has stopped editing before final review,
verification or integration. The manager inspects changes, including untracked
files, checks those results and, when appropriate, runs
`lodex run verify --target ID --json` to record verification. This writes central
Lodex state. It also executes the checkout's recipe/scripts with the manager's
execution permissions: inspect relevant changes first, and use a separately
restricted runner if arbitrary test code must be isolated. Do not describe it as
running under the worker's sandbox.

Perform commits/integration only within the user's authorized workflow. Stop
services and run applicable cleanup before Lodex removal; preview removal and
respect Git/ignored-file protections. Closing a Herdr pane/workspace is separate
from deleting the taskenv; do not use Herdr worktree removal for a Lodex-owned
checkout. Report per-task results and distinguish tested behavior from unverified
permissions or resource isolation.
