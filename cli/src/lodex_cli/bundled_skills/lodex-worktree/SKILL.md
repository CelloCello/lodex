---
name: lodex-worktree
description: Create, attach, inspect or remove local Git task environments with Lodex. Use for explicit local environment management, not history search or task tracking.
---

Use the installed `lodex` CLI, with `--json` for machine-readable results.
Resolve the current caller's absolute directory every time; there is no global current environment.

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

Use service stop and cleanup before removal where applicable; review known resources and Git state, including the warning that ignored files are deleted. Keep code changes, merge/rebase and task progress with the caller. Never edit registry files directly or infer identity from a remote, branch or session.
