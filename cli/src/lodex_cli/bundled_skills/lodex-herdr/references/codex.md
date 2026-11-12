# Codex manager and worker setup

Read this when either role uses Codex. The templates target the config-file
profile and named permission-profile interfaces inspected in Codex CLI 0.166.0;
they are starting points, not portable guarantees for every version or OS.
Check `codex --version`, `codex --help` and current official docs before adapting
them. Do not pin the user's model or reasoning effort.

- [Config profiles](https://learn.chatgpt.com/docs/config-file/config-advanced)
- [Permission profiles and their scope](https://learn.chatgpt.com/docs/permissions)
- [CLI arguments](https://learn.chatgpt.com/docs/cli/reference)
- [MCP and other settings](https://learn.chatgpt.com/docs/config-file/config-reference)

## Inspect and propose

The static worker template is a baseline, not a service-enabled launch policy.
For the persistent A/B/C workflow, prepare the taskenv first, then draft:

```sh
lodex worktree worker-config --target TASKENV_ID \
  --prepare-operation PREPARE_OPERATION_ID --profile lodex-worker \
  --uv-cache /observed/uv/cache --delegation GRANT_ID \
  --deny-socket /observed/herdr/control.sock --json
```

Omit `--delegation` for a project without delegated services. Repeat `--deny-socket`
for runtime control sockets; include the active core control socket as well as
any TUI socket. Use `--allow-host HOST` only for reviewed application access;
localhost permission is not a taskenv-port boundary. Missing required service
scripts or a changed prepare/grant recipe stop drafting. A changed grant requires
a new draft and stopped-worker resume, not an in-place credential swap.

`--deny-path /absolute/private/path` adds explicit read/write denials, for example
other management roots or agent credential/history directories. Review more-specific
rules when selecting such paths. After approval to trust this project's generated
checkout, `--trust-checkout` marks only that checkout trusted through CLI overrides
for this invocation; it does not save a global project-trust entry. It is off by
default. An unapproved trust dialog is a setup question, not a reason to answer
automatically or bypass sandbox/hook trust. Native resume still uses fresh settings.

The command writes a 0600 snapshot under `LODEX_HOME/worker-policies`, returns its
policy path and interpreter/agent/sandbox argv, and does not install/apply settings.
The launcher selects the approved config file and adds a unique per-launch
permission profile via CLI overrides. It preserves model/reasoning settings. No
`CODEX_HOME` config/profile file is rewritten for each task. The user must review
the concrete rules before their first application; subsequent task paths can use
the same previously approved rule contract without repeated permission questions.

For new taskenvs the draft denies central data, permits peer reads but not writes,
and opens only the assigned checkout, its own grant/runtime and reviewed cache
for writing. Shared Git metadata and workspace parents stay read-only; the latter
also cover tasks created after launch. Global temp is read-only, with a private
writable task temp. Legacy snapshots and runtime paths stay unchanged.
It enables network proxy enforcement with an explicit Unix
allowlist; with no `--allow-host`, no application TCP host is allowed. This is
different from merely setting Unix rules while disabling the proxy.
Selecting a delegated service with `allow_local_binding = true` enables local
binding regardless of its readiness probe. If omitted, `ready_port` retains
this inference; explicit `false` disables it. Services using an HTTP health
probe in `ready_argv` must request binding explicitly. Review the generated policy: Codex does not
restrict that capability to Lodex's allocated port. Keep explicit host allowlists
and repository-owned port/resource isolation; do not treat ports as a security boundary.

The draft requests disabling apps/plugins at the feature gate as well as discovered
entries, the implicit `codex_worktrees` and `codex_tui` MCP namespaces, image
generation, web search, hooks, JS REPL and both multi-agent feature variants.
Codex can expose built-in task/worktree tools without a
local MCP entry; disabling only discovered entries is insufficient. The draft
uses a disabled transport for that implicit namespace, never an active server.
These broad tool defaults are reviewable draft
behavior, not proof every host/managed capability was found. In particular,
disabling hooks may omit TUI integration metadata. Validate actual tools and
native session identification; do not keep a Herdr-control hook as a hidden
worker escape hatch. Legacy sandbox keys in inspected settings fail drafting
because they can override named permissions. Managed/remote settings and other
execution surfaces still require actual-session inspection. See official
[permissions](https://learn.chatgpt.com/docs/permissions) and
[environment/tool configuration](https://learn.chatgpt.com/docs/config-file/config-reference).

In observed Codex 0.167 interactive workers, the explicit `codex_tui` denial removed
TUI task-control tools, while collaboration tools remained advertised despite the
multi-agent flags. One explicitly authorized diagnostic child also launched with
no settings overrides: its own canary read succeeded, while peer checkout/runtime
writes and a central management canary read returned `EPERM`. This verifies only
those inherited command restrictions, not a disabled spawn capability or every
host tool. Tool visibility alone does not prove an escape, and configured
flags alone do not prove enforcement. Record the actual inventory and keep
unverified host-tool boundaries distinct from successful command-sandbox probes.
Do not claim complete host-tool isolation or use those routes to retry a denied
command. Additional diagnostic agents need authorization for their scope.

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

Replace the manager template's `/REPLACE_WITH_LODEX_HOME`, `/REPLACE_WITH_LODEX_WORKSPACE_ROOT` and
`/REPLACE_WITH_HERDR_SOCKET_PATH` keys with observed absolute paths. Do not pass
these markers to Codex or assume TOML interpolates shell variables. Quote paths
as valid TOML, including backslashes where necessary. Show both rendered files
and the exact launch commands for confirmation before installation or changes.
Installing the Lodex skill copies these assets only; it does not install profiles.

Keep three layers distinct: the skill describes the workflow; the selected config
profile supplies the role's baseline; the generated per-launch worker policy
supplies the actual taskenv paths, service route and tool restrictions. Merely
reading the skill or opening a pane applies none of those runtime grants.
The current launcher requires an existing worker config profile; its name need
not be `lodex-worker`. Starting only `codex -p lodex-worker` does not substitute
for the generated policy and guarded launch. Likewise, an external Codex App
coordinator uses its own active permissions; a CLI manager profile on disk does
not automatically grant them to the App conversation. Do not silently widen the
App or worker permissions to make those entry points appear equivalent.

Both templates include `"~/.cache/uv" = "write"` in their role's filesystem
table. This is an explicit shared-cache exception to the worker's checkout/temp
write boundary. Run `uv cache dir` in the intended manager and worker command
environments before setup; `UV_CACHE_DIR`, `XDG_CACHE_HOME`, uv configuration or
CLI flags may select another path. Adapt the grant to that observed cache root,
not the whole `~/.cache` directory. An override to a task-specific cache is a
different setup choice; do not silently reset it or keep unnecessary grants.

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
  a separate OS/container. Beyond checkout/temp writes, the worker template
  deliberately permits the reviewed shared uv cache. Use task-specific locations
  for other caches, temporary files and output. If shared temp access is
  unacceptable, adapt and validate explicit restrictions
  with a task-specific writable temp path before promising isolation.
- Share uv's package cache while keeping each checkout's virtual environment
  separate. With the shared-cache grant, ordinary manager and worker uv commands
  need no `UV_CACHE_DIR` injection through recipes, pane env or command prefixes
  when uv resolves to the granted path. Cache writes are not restricted to safe
  uv operations by the filesystem grant: a worker can also alter shared artifacts.
  Use task-specific caches when that wider write scope is unacceptable. Workers
  must not clean/prune the shared cache or edit its internals. The manager
  coordinates maintenance through uv when other uv commands are stopped; uv
  0.6.6 does not support concurrent cleanup. See [uv cache safety](https://docs.astral.sh/uv/concepts/cache/#cache-safety).
- Optional [service delegation](service-delegation.md) needs separately reviewed
  access to its returned runtime root and Unix sockets. Protect central state and
  other grants from reads as well as writes; keep access to the assigned checkout.
  The baseline template does not enable this. A helper's `--allow-unix-socket`
  probe is not proof that an agent loaded equivalent profile settings.
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
- The manager also needs `network.allow_local_binding = true`: Lodex's port
  allocator briefly binds loopback sockets while creating/attaching taskenvs.
  This does not start application services, but the capability itself is broader
  than the allocated ports and must be reviewed at setup. Verify an ephemeral
  loopback bind before creating taskenvs. On `partial_create`, repair/attach the
  returned checkout after fixing the setup; do not create a duplicate taskenv.

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

For each worker, use the generated policy's `launcher_argv` with its policy path
and task file through the selected [TUI](tui.md#interactive-worker) or
[core/App](core.md#interactive-worker) adapter. Those adapters start the shared
launch guard in the assigned checkout; the guard applies the generated policy
and holds the taskenv's writer lock. A direct `herdr agent start` with only the
static worker profile omits these protections and the delegated service route.

Use observed paths/IDs and an argument array or correctly shell-quoted command.
Do not pass `--worktree`, drop generated policy arguments on error, or add overrides
that undo the reviewed settings. For continuation, follow [lifecycle](lifecycle.md):
stop the old worker, then launch the new policy with its original native UUID.
The guard verifies checkout ownership before first binding and rejects a different
UUID once one is recorded. Check effective cwd and permissions after resume;
agents already running outside the guard need separate
reconciliation before this workflow can claim single-writer protection.

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
| Manager and worker resolve `uv cache dir` to the reviewed shared cache | Same granted path |
| Manager and worker initialize that cache via `uv run --no-sync ruff --version` in a prepared Python checkout | Allowed |
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
