---
name: lodex-worktree
description: Create, attach, inspect or remove Lodex task environments on explicit request or within the same authorized task. Default ordinary development to the current repo.
---

Work in the current repo/checkout by default. Enter this workflow only on explicit
user request. Prior authorization continues only for the same task and within its
original environment and operation scope. Installed tools, `.lodex` files and
ordinary coding, testing or parallel work do not authorize taskenv setup
(registration, attachment, checkout creation or `prepare`). Inspection alone
does not authorize setup or service startup.

Use the installed `lodex` CLI, with `--json` for machine-readable results.
Resolve the current caller's absolute directory every time; there is no global current environment.
These are management operations. A restricted B/C should send environment-management
needs to coordinating session A; never unset delegation or change profiles to get
registry access. Standalone worktree management needs no Herdr runtime.

- Register: `lodex project add NAME /absolute/repo [--config /absolute/project.toml] --json`.
- Create: `lodex worktree create NAME --ref REF --branch BRANCH --json`.
- Attach existing main, external or detached checkout: `lodex worktree attach NAME /absolute/checkout --json`.
- Resolve: `lodex context --target /absolute/directory --json`.
- Inspect records even when missing: `lodex worktree inspect --target ID --json`.
- List: `lodex worktree list --json`.
- Preview deletion: `lodex worktree remove --target ID --json`.
- Execute authorized deletion with `--yes`; use `--force` only when the user explicitly chooses to discard Git-protected contents. Main and external checkouts cannot be removed.
- Preview forgetting: `lodex worktree forget --target ID --json`; `--yes` removes registration, not resources.

Return the taskenv ID and absolute checkout path; do not claim the agent workspace
was switched. Configuration fallback preserves existing project.toml and copies
only a missing TOML from the registered or explicit source. Git checkout supplies
tracked files normally; missing dependencies need repo-specific preparation.
Source `.env` files and arbitrary shell credentials are not automatically delivered.
Follow the project's chosen settings/preparation method. For agent dispatch, use
a successful prepare handoff before opening the worker; creating a checkout alone
does not establish readiness. Keep the same taskenv ID when repairing preparation.

Before cleanup, agree that any agent has stopped editing; a completed turn does
not authorize teardown. Review known resources and project ordering: cleanup may
need running services/settings. When a saved worker policy applies, use the
task-bound `lodex cleanup --target ID --worker-policy PATH --json`, including after
agent exit. If a restricted worker's policy is unavailable, recover equivalent
execution limits with A before cleanup. Plain cleanup executes in caller
permissions and is not an elevated retry. Retain the checkout and handles after
failure or uncertain results.

Complete required cleanup, service stops and terminal recording/ACK before ending
delegation/controllers. Confirm the worker program has exited before deleting its
checkout; coordinate through A when it owns the runtime mapping. Preserve shared
resources according to the project contract. Then perform separately authorized
removal with Git protections, including the warning that ignored files are deleted.
Keep code changes, merge/rebase and task progress with the caller. Never edit
registry files directly or infer identity from a remote, branch or session.
