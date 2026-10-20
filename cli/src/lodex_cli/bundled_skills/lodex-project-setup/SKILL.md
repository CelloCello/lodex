---
name: lodex-project-setup
description: Connect a repository to Lodex by inspecting local evidence, drafting project.toml and testing explicit environment commands. Use for initial setup or configuration changes, including repositories with no services.
---

Inspect AGENTS.md, README, package manifests, configuration readers, scripts and Compose files before proposing `.lodex/project.toml`. Map each proposed tool, command, environment variable, service and cleanup action to a file or documented command. Identify unknown secret references, isolation needs and destructive effects; ask the user to resolve those before the dependent trial. A repo without services needs only prepare/verify; do not invent services.

Reuse existing repo operations, but check who owns their lifecycle before invoking
them. A script that also creates/closes Git worktrees, copies a primary `.env`,
allocates its own ports, or updates another registry must not silently duplicate
Lodex's responsibilities. Keep repo-specific DB/queue/migration/backup policy in
repo scripts; use Lodex's explicit taskenv inputs and resource-result contract.
Verify DB and queue isolation with test data, not merely different service ports.

Keep newly created Lodex-specific integration files under `.lodex/`: scripts in
`.lodex/scripts/`, and supporting files such as `compose.yml` alongside
`project.toml`. Reuse existing project scripts in place. The developer or an
authorized agent creates and maintains integration scripts; the CLI only creates
the TOML skeleton or copies an explicit TOML recipe. Commit the integration files
and include them in the ref used for new worktrees. Add narrow ignore rules for
runtime records (for example, `.lodex/.gitignore` can ignore `/resource-owner.json`);
do not ignore the whole directory or commit real secrets. Show any necessary Git
or ignore changes within the user's authorized scope.

For initial registration, `lodex project add NAME /absolute/repo --json` creates
a missing `.lodex/project.toml` skeleton; `--config PATH` copies an explicit recipe
only when the target is missing. Existing files are validated and preserved,
including on repeated registration; invalid files require correction. The response
reports the configuration path/method and, for a new skeleton, the next editing
step. Registration does not attach the checkout or make its services ready.
Fill the skeleton from repository evidence, then attach and trial the configured
commands. New registrations use the checkout's TOML as the source for worktrees.

Draft schema version 1 TOML using these supported fields:

```toml
schema_version = 1
tools = ["python3"]
[env]
ENV_NAME = "task-${LODEX_TASKENV_ID}"
[ports]
PORT = 0
[secrets]
API_TOKEN = "secret:project-api-token"
[commands.verify]
argv = ["python3", ".lodex/scripts/verify.py"]
scripts = [".lodex/scripts/verify.py"]
[services.web]
argv = ["python3", ".lodex/scripts/server.py"]
scripts = [".lodex/scripts/server.py"]
ready_port = "PORT"
url = "http://127.0.0.1:${PORT}"
```

This is a format example, not evidence those scripts exist. `commands` may contain prepare, verify, cleanup and other names. argv executes directly, without implicit shell. Repo scripts decide setup order, migrations and retry behavior. `${NAME}` interpolates explicit taskenv inputs; secrets must be read from process env, never argv/URLs. Required scripts must be declared so absent copied-recipe dependencies produce a useful error. Ports are saved; `0` requests allocation. Every service requires argv and is a process Lodex can start and stop. Third-party/shared dependencies use env and secrets; per-taskenv mock servers are ordinary services with allocated ports. Do not generate `external` fields. Old URL-only records are read-only; use a new service name when replacing one with a managed process.

Show proposed changes to existing configuration before applying them. Preserve user edits and existing values. Missing configurations can be copied independently during create/attach/prepare; no .env or scripts are copied, no Git index or ignore changes occur implicitly.

Validate with `lodex project add NAME /absolute/repo --json` and `lodex worktree attach NAME /absolute/repo --json`. Trial only evidence-backed, authorized commands:

```
lodex env show --target ID --json
lodex secret list --json
lodex secret set project-api-token
lodex prepare --target ID --json
lodex run verify --target ID --json
lodex operation list --target ID --json
lodex operation logs OPERATION_ID --json
lodex cleanup --target ID --json
```

Edit ordinary `[env]` values and `[secrets]` mappings directly in each checkout's TOML; there are no DB overrides or env set/unset/secret ref/unref commands. `env show` previews resolved values and secret references; it does not read an existing `.env`. Secret list/set/remove manage central stored names without `--target` or a registered project. In the example, `secret set project-api-token` supplies `API_TOKEN` through `secret:project-api-token`.

Ask users to enter real secrets through hidden input or a trusted stdin pipeline; do not put values in chat, argv or project.toml. Values are stored in plaintext SQLite under `LODEX_HOME`, with private file permissions and no keychain or master key. Treat the management DB and backups as sensitive; do not include them in diagnostic bundles. `secret:NAME` references share one value across taskenvs using the same management DB. `env export --output .env` requires ignored output when secrets are included and rejects tracked or handwritten/modified files. Explain necessary ignore changes and apply only within the user's scope. `secret remove NAME` previews deletion of the shared SQLite value; `--yes` executes it. Cleanup/remove/forget and removing a TOML mapping do not delete secrets. Updated values take effect on subsequent command/service starts or exports, not already-running processes. Older `keychain:` references must be changed and values set again; do not read or migrate existing Keychain items automatically.

For resource reporting, scripts may write UTF-8 JSON to `LODEX_RESULT_FILE` containing `resources` (each with name, kind, id, scope exclusive/shared and state present/removed/unknown) and `urls` (HTTP(S) strings). Results are observations, not a complete resource inventory. Interrupted/unknown operations are not retried automatically. Missing cleanup scripts require restoration or manual handling, not a success claim. Finish by reporting evidence, trials performed, unresolved configuration and the taskenv ID/path.
