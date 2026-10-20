# Codex manager and worker setup

Read this when either role uses Codex. The templates target the config-file
profile and named permission-profile interfaces documented for Codex CLI 0.162.1;
they are starting points, not portable guarantees for every version or OS.
Check `codex --version`, `codex --help` and current official docs before adapting
them. Do not pin the user's model or reasoning effort.

- [Config profiles](https://learn.chatgpt.com/docs/config-file/config-advanced)
- [Permission profiles and their scope](https://learn.chatgpt.com/docs/permissions)
- [CLI arguments](https://learn.chatgpt.com/docs/cli/reference)
- [MCP and other settings](https://learn.chatgpt.com/docs/config-file/config-reference)

## Inspect and propose

Resolve the actual source checkout, Git common directory, Lodex state root and
Herdr session socket. Use `git rev-parse --path-format=absolute --git-common-dir`
in the source checkout. Lodex uses `LODEX_HOME`, defaulting to `~/.lodex`; prefer
the active session's setting and Lodex's observed paths over an assumed default.
Within a Herdr pane, inspect `HERDR_SOCKET_PATH` and session context. If the socket
is not explicit, use the installed Herdr documentation/status to resolve it; a
named session may use a different socket. Do not invent or enumerate unrelated
sessions to find a target.

Inspect applicable user/project/profile and managed Codex settings, summarizing
permission keys and enabled tool identities without printing secrets. Identify
shell aliases or launch overrides that would change the result. The manager and
workers are separate sessions: approval or writable roots in one do not establish
the other's permissions.

Use these assets to draft the proposed files under the actual `CODEX_HOME`
(default `~/.codex`):

| Asset | Suggested config profile name | Destination filename |
| --- | --- | --- |
| [Manager](../assets/lodex-manager.config.toml) | `lodex-manager` | `lodex-manager.config.toml` |
| [Worker](../assets/lodex-worker.config.toml) | `lodex-worker` | `lodex-worker.config.toml` |

The `-p` argument selects a **config file**. Its top-level `default_permissions`
then selects the **permission profile** defined in that file. Existing suitable
names may be reused; keep the actual manager/worker selection explicit.

Replace the manager template's `/REPLACE_WITH_LODEX_HOME` and
`/REPLACE_WITH_HERDR_SOCKET_PATH` keys with observed absolute paths. Do not pass
these markers to Codex or assume TOML interpolates shell variables. Quote paths
as valid TOML, including backslashes where necessary. Show both rendered files
and the exact launch commands for confirmation before installation or changes.
Installing the Lodex skill copies these assets only; it does not install profiles.

## Adapt the boundary

- Start the manager at the source repo, not a parent containing unrelated repos.
  It writes that checkout, the active Lodex state root, and the Git common
  directory needed for worktree/Git operations. The template's `.git` override
  covers an ordinary source checkout; an external common directory needs its own
  narrowly scoped rule. Resolve symlinked plans and grant their real destination
  only when the manager must edit them. Do not grant an entire notes vault.
- Explain the central-state grant: the Lodex root contains shared records,
  plaintext stored secrets and potentially other projects' taskenvs. The template
  trusts the manager with that root. If the user does not accept that scope, stop
  for a different management boundary; do not quietly grant it to workers.
- Workers write their one runtime checkout. Do not add the source repo, Git common
  directory, Lodex root or the taskenv parent as writable roots. Preserve inherited
  `.git`, `.codex`, `.agents` and `.aws` protections. `:workspace` also permits
  system temp writes and broad reads; this is not a confidentiality boundary or
  a separate OS/container. Prefer per-task temporary/cache/output locations. If
  shared temp access is unacceptable, adapt and validate explicit restrictions
  with a task-specific writable temp path before promising isolation.
- Worker `approval_policy = "never"` keeps denied shell operations from waiting
  for interactive approval; it does not grant access or prevent all user questions.
  Workers report missing capabilities to the manager. Prepare dependencies first.
  The manager uses `on-request` for exceptional needs; do not promise zero prompts.
- The manager template includes an optional, commented
  `approvals_reviewer = "auto_review"`. With user confirmation, enable it to route
  eligible manager approval requests to Codex's automatic reviewer while keeping
  `approval_policy = "on-request"` and the named permission profile. Review may
  deny requests or require user involvement; it does not grant blanket approval
  or change the sandbox. Keep workers on `never` so missing capabilities return
  to the manager. Prefer this setting over `--approve-for-me`, which also selects
  the older `workspace-write` sandbox path. See the
  [approval reviewer reference](https://learn.chatgpt.com/docs/config-file/config-reference).
- Keep Herdr session control with the manager. A socket grant enables control
  operations, including launching commands in other panes, not just status reads.
  Deny inherited Herdr socket grants for workers. Merely hiding `HERDR_ENV` or
  avoiding a CLI command is not an access boundary.
- Inspect effective MCP, plugin, browser/computer-control, connector, hook and
  other execution capabilities. Disable unnecessary worker capabilities through
  their supported per-profile controls; for each actual MCP server use
  `[mcp_servers.SERVER_ID] enabled = false` when it is not needed. Do not copy the
  author's tool IDs or assume disabling MCP also disables plugin-provided tools.
  Report any capability that cannot be restricted before dispatching sensitive
  work. Command sandbox rules do not govern every tool surface.
- The manager template enables the network proxy for destination filtering and
  allows only the resolved Herdr socket in the template itself. Inspect inherited
  domain/socket allowances too; add dependency hosts or local endpoints only as
  required. The worker baseline disables command network access. Tests needing
  local services require an explicitly reviewed policy: allowing localhost does
  not isolate one task's service from other ports. Docker/control sockets and
  broad network grants are additional capabilities, not routine fixes.

Permission profiles are layered, not isolated replacements of base config.
Remove conflicts only with confirmation: `sandbox_mode`,
`sandbox_workspace_write`, `--sandbox`, or `--approve-for-me` can select the older
sandbox path instead. Also check inherited writable roots, same-name permission
profile entries, shell environment overrides and approval rules. Managed policy
can impose further restrictions. On incompatible versions, explain the supported
configuration or required upgrade; never fall back to Full Access or launch
without the selected profile.

## Apply and launch

After confirmation, create missing profile files or apply the reviewed diff to
existing ones. Preserve unrelated content and never replace the user's entire
base config with a template. Record any departure from the template and its reason.
Changing a file does not reconfigure the already-running manager or workers.

Start a new manager session in the intended Herdr pane with the approved profile:

```bash
codex -p "$manager_profile" -C "$source_repo"
```

If the current manager has insufficient permissions, provide this restart/handoff
instruction and preserve task context. Do not launch an unrestricted replacement
from a restricted session to work around its controls.

For each taskenv, follow the Herdr skill to create an available shell pane using
the checkout path as `--cwd`. Use its returned ID to launch:

```bash
herdr agent start "$agent_name" --kind codex --pane "$pane_id" -- \
  -p "$worker_profile" -C "$taskenv_path"
```

Pass only observed, shell-quoted values. Check `herdr agent` for installed syntax.
Do not pass `--worktree`, omit `-p` on error, or append sandbox/approval overrides
that undo the approved profile. Reusing a Codex session requires checking that
its effective cwd and permissions still match; do not assume resume adopts new
profile contents. Agents already running before setup need separate reconciliation.

## Validate before relying on isolation

Do a bounded setup check after installation or changes to profiles, roots, tool
capabilities or runtime versions. Do not repeat the full check for every ordinary
task. Use the installed client's supported permission/status inspection and, when
available, `codex sandbox --help` to construct harmless probes under the actual
profile. Run probes on disposable fixture files, never on live sibling work.

Verify these outcomes, keeping manager and worker results separate:

| Probe | Expected |
| --- | --- |
| Worker reads source plan and writes its checkout fixture | Allowed |
| Worker writes a fixture in a sibling checkout or central state | Denied |
| Worker writes shared Git metadata or controls the Herdr socket | Denied |
| Worker uses an alternate execution tool | Unavailable or separately constrained |
| Manager reads Herdr state and runs an authorized Lodex operation | Allowed |
| Worker runs the agreed direct tests with task-specific inputs | Allowed |

For socket checks, use a non-mutating status/read request for the intended session;
never send terminal input as a negative probe. Check actual applied permissions,
not just whether the TOML parses, `-p` appears in argv, or Herdr reports ready.
Nested-sandbox restrictions may prevent a probe; report that as unverified and
arrange validation from the intended runtime instead of disabling restrictions.

Before productive dispatch, confirm the launched worker's cwd, configuration and
tool surface match the validated setup. Record the result in the existing task
record/conversation. If a boundary fails, stop affected work and propose the
specific correction; configuration changes still need the scoped confirmation.
