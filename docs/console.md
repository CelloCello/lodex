# Local console

The console uses the same management database and Python core as the CLI. It is
optional; environment management and history do not require it.

For a guided first run after installation, follow the
[first website walkthrough](manual-validation.md): clone a small MDN site,
register it with the CLI, then use the project-setup, worktree and services skills
to configure, develop and clean up an environment. Console is primarily used to
observe the resulting state throughout that agent-driven workflow.

## Install and open

Build the release set following the [installation guide](../README.md#installation).
From that checkout, install the optional Console extra (also use this to add it
to an existing CLI installation):

```bash
cd /absolute/path/to/lodex
uv tool install --force --find-links dist 'dist/lodex-0.2.0-py3-none-any.whl[console]'
```

After installation, start the console from any directory:

```bash
lodex console --port 8765
```

Keep the terminal running and open the complete URL it prints, including
`#token=...`; opening only `http://127.0.0.1:8765` in a fresh tab does not
authenticate it. Omitting `--port` selects an available loopback port. If 8765 is
already occupied, stop your earlier console or choose another port.

The access token is in the URL fragment (not sent
in HTTP URLs); the browser keeps it in tab session storage. Restarting the server
creates a new token, so open the newly printed URL after each restart. Do not
share the access URL. API reads require the token;
writes also require the exact same Origin. Host validation rejects DNS rebinding,
the server ignores proxy headers, and the UI uses only bundled assets.

Installed use needs no Node.js, pnpm or Vite server. This console shows your actual
management registry, shared with the CLI for the same `LODEX_HOME` (default
`~/.lodex`); it does not load demonstration records. Press Ctrl+C in its terminal
to stop the console. Managed services continue running; see the lifecycle details
below for in-progress commands.

## Navigate and operate

Environments is the default page. Search by branch, project, path or ID, and filter
by project or status. Projects provides repository registration, configuration
sources, worktree creation and attaching existing checkouts. Registration does
not implicitly create, prepare or start an environment.

Open an environment for Services, Operations, Configuration, Resources, and
Cleanup & removal. Services keeps process state, URLs, start/stop and logs together;
Operations runs configured commands and shows recorded outcomes. Configuration
shows resolved non-secret values and references, exports `.env`, and changes
declared ports. Cleanup/removal confirmations show the affected path, Git changes,
services and known resources, with optional raw data and a separate force choice.

The URL preserves the selected environment and tab through reloads and browser
history; list filters are also in the URL. These routes are usable within an
authenticated console tab. The mobile navigation menu exposes the same pages.
The header's theme selector offers System, Light and Dark. System is the default
and responds to OS appearance changes. An explicit Light or Dark choice survives
reloads using browser local storage for that origin (scheme, host and port).
Reuse `--port 8765` and the same host to retain the choice across server restarts;
a different origin starts with System unless it already has a saved preference.
When storage is unavailable, switching still works for the current page.
`Checkout available` means the directory is present, not that preparation or
service startup succeeded. The current branch and commit are observed at inspection
time; they do not determine taskenv identity. Missing or invalid configuration is
shown without hiding previously recorded services or resources.

Services represent processes Lodex can start and stop, including per-environment
mock servers. Third-party/shared dependency connections belong in env/secrets.
Legacy external URL records remain visible with migration guidance and no process
controls; use a new service name for a managed replacement. Old `external` recipe
fields produce an explicit configuration error rather than being silently ignored.

The Secrets page operates independently of projects. Values are sent in request
bodies, cleared from the form after submission and never returned. The local
management SQLite database stores values in plaintext under private permissions;
updating a shared name affects the next command/start/export, not running processes.

Closing a tab does not stop services or replay a submitted action. Reopening it
queries recorded results. Commands execute in a separate foreground worker so
the API can continue serving reads. Stopping the console interrupts pending
request workers after a short grace period; the existing operation runner saves
known interrupted outcomes. Abrupt process loss can leave an outcome unknown or
a worker still finishing: inspect before explicitly retrying. There is no durable
queue, automatic continuation or automatic retry. Managed long services are
independent of the console and remain accessible through a new CLI caller.

Remove first shows the checkout path, Git status, services and known resources.
Removal retains the registry record for inspection; forget it separately when no
longer needed. Force removal is a separate unchecked choice; Git and external/main-checkout
protections remain in the core. Forget removes registration without deleting
services, resources or shared secrets. Cleanup executes the repository's command
and does not implicitly stop services or delete a worktree.

## Update the installed console

The installed `lodex console` serves the frontend bundled in the installed Server
wheel. Changes in a source checkout, including `pnpm --dir console/f2e run build`,
do not update that installed copy. To install the current checkout's UI and Python
packages, rebuild the release set and reinstall with the Console extra:

```bash
cd /absolute/path/to/lodex
uv sync --locked
pnpm --dir console/f2e install --frozen-lockfile
uv build --all-packages
uv tool install --force --reinstall --find-links dist 'dist/lodex-0.2.0-py3-none-any.whl[console]'
```

Keep `--reinstall` when rebuilding the same package version so the dependency
packages, including Console Server, are reinstalled too. Stop the old console
process with Ctrl+C, start `lodex console --port 8765` again, then open its new
token URL. These wheel names match the current 0.2.0 release; use the corresponding
filename when the package version changes.

## Development and distribution

First build the release set as described in the [installation guide](../README.md#installation)
when installing from a checkout. For workspace development:

```bash
uv sync --locked
pnpm --dir console/f2e install --frozen-lockfile
pnpm --dir console/f2e run typecheck
pnpm --dir console/f2e run build
pnpm --dir console/f2e test
uv run python scripts/verify_distribution.py
```

To inspect the checkout's built UI against your real management registry, run
`uv run lodex console --port 8765` from the repository root and open the printed
URL. After frontend edits, run the frontend build again and reload the browser.
For a disposable repository and service instead, follow the
[manual verification walkthrough](../console/f2e/README.md#manual-verification).

Vite writes the production build into `console/server/src/lodex_console/static/`.
`uv build --all-packages` rebuilds those assets automatically through the Server
build hook, then produces Core, CLI and Console Server wheels and source
distributions. A wheel built from the Server sdist uses its bundled assets.
Installed usage needs neither Node nor a Vite server. All four Skills belong
to the CLI package. The distribution check installs the packages in fresh
temporary virtual environments, exercises Skills under a mocked home directory,
reinstalls it, checks preserved management data, and serves the packaged UI from
outside the source checkout. Existing schema migration coverage lives in the
management tests; reinstalling the same wheel is not a cross-version migration test.

The Playwright suite owns its temporary Git repository, management database and
loopback server. It checks CLI → browser → CLI state, reload during a command,
secret masking, delete confirmation, and desktop/mobile layout. The Python console
tests additionally cover access/origin rejection, malformed secret requests,
shared locks, missing configuration and server shutdown during a command.
