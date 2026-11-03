---
name: lodex-herdr
description: Set up or coordinate persistent coding-agent sessions in Lodex task environments through Herdr TUI or herdr-core/App, with scoped service control. Use for the combined workflow and parallel tasks, not standalone history search or ordinary worktree management.
---

# Lodex + Herdr

Keep session A in the source checkout. A prepares taskenvs and coordinates;
B/C are interactive sessions in distinct Lodex checkouts. The user can work in
any session and return to A. A completed turn leaves B/C available for follow-up.
Lodex owns environment identity, configuration and services; Herdr owns terminals;
the skill connects them. The service controller is a program, not another agent.

## Select and review setup

Use the user's selected runtime and agent. TUI uses `herdr`; core uses `hc`;
Herdr App presents core terminals. They do not share TUI agent identities. Never
switch runtimes after an uncertain launch or create a second Herdr-owned worktree.

Read [Codex settings](references/codex.md) for Codex. Other agents need their own
validated permission/launch contract; `worker-config` currently drafts Codex only.
Inspect installed help and effective tools. Do not substitute an agent, pin its
model, replace global defaults or install profiles without the applicable approval.
Standing approval for a reviewed setup can cover generated paths for subsequent
tasks within that scope; a new host/tool/root or wider grant needs scoped review.

Choose the runtime reference before live control:

- [TUI](references/tui.md): requires the actual caller's `HERDR_ENV=1`; preserve focus.
- [Core and App](references/core.md): explicit local core context and terminal IDs.

Read the upstream runtime skill/current help. Setup and code review can continue
outside Herdr, but do not inspect/control an unrelated focused user session.

## Prepare and hand off

1. Resolve project, base ref, task boundary and resource contract. Use Lodex's
   observed IDs/absolute paths, not branch or pane labels. Use project-setup for
   missing recipes. Honor the project's existing startup, settings and resource
   ownership choices: shared DBs/data and project-owned `.env`/secret tools are
   valid. Preparation must deliver usable settings to the new checkout. Record
   shared effects and cleanup ownership; per-task DBs and Lodex secret storage are
   project choices. The shared uv cache is an explicit writable exception, not
   full isolation; workers do not prune it.
2. Reuse an appropriate taskenv or create a distinct branch/checkout through
   Lodex. Keep the returned ID before further work. Run `lodex prepare --target
   ID --json`; it exports optional `[taskenv] env_file` before the recipe. Only a
   successful prepare has a handoff. Fix/retry the same ID on failure; never
   blindly create another checkout or claim its presence means it is ready.
3. For selected taskenv-owned services, review the recipe and start an independent
   controller terminal using [service delegation](references/service-delegation.md). Keep
   its actual runtime handle and returned grant information. No services means
   no controller is needed. The controller never runs repo code.
4. Draft `lodex worktree worker-config` with the successful prepare operation,
   approved config profile, observed uv cache, grant ID and actual control socket
   paths to deny. Review its filesystem/socket/host/tool scope. It writes a
   protected policy and returns launch arguments, without installing or applying
   settings. Check required paths/hosts/tools against the actual worker scope.
   Report a capability gap if the project's chosen startup method needs broader
   access; resolve the choice with the user before dependent work. Project startup
   passing in A does not prove B/C compatibility. Invalid setup fails; do not use
   manager permissions or Full Access, silently change startup tools, or give a
   worker broad daemon control as a fallback.
5. Create a focused task text containing the handoff ID/path/project/base commit,
   requested result, direct test/config-loading instructions, authorized services,
   acceptance and return information. Use excerpts if source plans are inaccessible.
   Do not put secret values or credential tokens in prompts, argv or labels.
   Workers use their handed-off context; `lodex context` still needs the registry.
6. Use the chosen runtime reference to launch B/C with the protected policy and
   task file. Record runtime kind, host/session/socket, actual pane/terminal and
   native agent session ID when observed. The launch guard prevents a concurrent
   worker for that taskenv; unknown exits require reconciliation. A command being
   admitted is not proof the task arrived or effective permissions loaded.
7. Confirm cwd, applied permissions, tool surface and receipt of the first task
   before productive work. Report denials and fix the reviewed setup; never use
   another execution channel to bypass them. Repeat for C with a different taskenv.

## Coordinate, continue and finish

Use runtime waits/read surfaces and bounded output. A refreshes actual state and
latest summaries before following up, especially after the user works directly in
B/C. Sessions do not share conversation memory. A timeout is not proof input was
lost; inspect before resending. Keep blocked approval/question UIs for the user
unless the exact response is already authorized.

B/C use delegated `service start/stop/list/inspect/logs` autonomously. Restart is
stop then start. Ordinary code edits are allowed; recipe changes require review
and a new grant. Running processes and old exported settings do not refresh when
project secrets change. Controller availability follows active taskenv use, not
A's reasoning turn. Keep controllers outside core's worker-child wait group.

Follow [lifecycle and recovery](references/lifecycle.md) for replacing a grant,
stopping the old worker and resuming the same native session with new settings,
or for explicit cleanup. Neither settled status nor a completed turn authorizes
revoke, process exit, cleanup, commit, integration or taskenv deletion.

Before final review/integration, agree that the worker has stopped editing and
inspect tracked/untracked changes and tests. `lodex run verify` executes repo code
with its caller's permissions; it is not automatically the worker's sandbox.
For explicit teardown, inspect changed cleanup code and use the task-limited
runner. Preserve checkout/handles after failure. Report actual checks separately
from unverified agent/tool/network/resource boundaries.
