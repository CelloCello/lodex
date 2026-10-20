# Console frontend

The browser UI for Lodex's optional Console: inspect environments, run configured
commands, and view or control services while working with a coding agent. It uses
the same management state as the CLI through the Console server.
See the [main README](../../README.md) for the overall workflow and
the [Console guide](../../docs/console.md) for installed usage.

React/TypeScript source lives in `src/`. Vite builds into the server package's
`src/lodex_console/static/`; these generated assets are shipped with the server.
Vite's public assets come from `docs/assets/` at the repository root, so the
Console brand and favicon share the README's `lodex-logo.svg` source.

Building requires Node.js 20.19+ or 22.12+ (Vite 8's supported ranges) and the
pnpm version pinned in `package.json`. Type checking uses TypeScript 7's native
`tsc`; Vite handles bundling separately. When switching package managers,
remove the existing `console/f2e/node_modules` directory before installing to
avoid stale dependencies. From the repository root:

```bash
pnpm --dir console/f2e install --frozen-lockfile
pnpm --dir console/f2e run typecheck
pnpm --dir console/f2e run build
pnpm --dir console/f2e exec playwright install chromium --only-shell
pnpm --dir console/f2e test
```

Install the matching browser again after upgrading Playwright.
Playwright cases live in `tests/` and exercise the frontend, HTTP server and CLI
together. Their Python fixture lives in `console/tests/` and uses the root Python
workspace.

## Manual verification

For everyday usage after installation, follow the
[first website walkthrough](../../docs/manual-validation.md). For broader checks,
see [advanced manual validation](../../docs/manual-validation-advanced.md).
The fixture below is a visual check with pre-created data and automatic cleanup on exit.

For installed usage and release updates, follow the
[Console guide](../../docs/console.md#install-and-open). To manually inspect the
checkout with disposable data, run the existing browser fixture from the repository
root after installing frontend dependencies as above:

```bash
uv sync --locked
pnpm --dir console/f2e run build
uv run python console/tests/browser_fixture.py
```

Keep that terminal running and open
[the fixture Console](http://127.0.0.1:18765/#token=browser-fixture-token).
The fixture owns a temporary Git repository and management registry, registers
`browser-fixture`, creates `feature/console`, and starts an HTTP service. Its
prepare, verify and cleanup commands print demonstration output; they do not
validate a real project's external resources. Port 18765 must be free by default.
To keep a manually opened fixture running while executing the browser suite, use
a different free port, for example `LODEX_TEST_PORT=18766 pnpm --dir console/f2e test`.
The same variable works with the Python fixture command; adjust the browser URL
to that port when launching it manually.

| Check | Steps and expected result |
| --- | --- |
| Appearance | Try Light, Dark and System across lists, details and the New worktree dialog. An explicit theme survives reload; System follows OS appearance changes. Text, placeholders and focus indicators remain readable. |
| Navigation | Open a project name directly, toggle its tree independently, and search outside the six-item preview. Source information is under Details on the same list page. Filters, pagination and detail tabs survive reload/back; legacy project links redirect to the combined page. |
| Services and commands | Open the fixture HTTP URL, read logs, Stop and Start its service; run prepare and verify in Operations. State and execution output update. Reload after completion does not run a command again. |
| Secrets | Save a dummy value, confirm the input clears and the value is not shown in the list, then delete it. |
| Create and remove | Create `feature/manual-ui-check`; it should not start services automatically. Inspect the removal scope, cancel once, then remove that new worktree. Force starts unchecked. Removal retains its evidence record; Unregister is a separate action. |
| Keyboard and mobile | Use Tab and Esc in dialogs and check focus returns to the opener. At about 390px width, check both themes, mobile navigation and forms for overlap or page-wide horizontal overflow; wide data tables may scroll within their container. |

Press Ctrl+C in the fixture terminal when finished. Its shutdown stops fixture
services and removes the temporary directory. All fixture data is disposable.

## UI and navigation

The console uses React, Tailwind CSS and locally owned shadcn/ui components.
Its sidebar, page headers and data-table layout follow the patterns in
[shadcn-admin](https://github.com/satnaing/shadcn-admin); domain pages are specific
to Lodex. The admin example application and its authentication, charts and stores
are not bundled.

- `src/app.tsx`: application shell, responsive navigation and routes.
- `src/pages/`: Overview dashboard, environment list/detail, projects and shared secrets.
- `src/components/project-navigation.tsx`: persistent project tree, full-registry search and shared desktop/mobile expansion state.
- `src/lib/environments.ts`: shared attention, service grouping, environment ordering and latest-operation semantics.
- `src/components/ui/`: shadcn primitives generated with `components.json`.
- `src/components/`: environment forms, scope confirmations and shared displays.
- `src/lib/console.tsx`: TanStack Query overview/detail reads and explicit action
  submission, without write retries.
- `src/lib/queries.ts`: shared typed `queryOptions`, query keys, and polling policy.
- `src/api.ts`: HTTP boundary and API response types.
- `src/style.css`: neutral light/dark theme tokens and responsive layouts. Green,
  amber and red identify operational states alongside explicit text and icons.
- `src/lib/theme.ts`: system preference tracking and local theme selection.

Overview and the selected environment detail share typed query definitions between
hooks and manual refresh. A missing target uses `skipToken`; details are enabled
only for a registered environment. The two queries use separate keys and poll
every three seconds, including while the page is hidden. Reads pass an abort
signal to fetch so switching environments cancels an unused detail request.
Cached data retains its observation time while a refresh is pending. Query errors
follow the active queries and clear after recovery. Detail errors also clear
when leaving their environment.
They remain dismissible; a later polling failure can report a new error.

Queries use `networkMode: "always"` because the loopback server can be reachable
without an internet connection. Automatic retries, focus refetching and reconnect
refetching are disabled. Manual Refresh and successful or failed write actions
cancel earlier reads and invalidate cached state. Refresh reads the overview
first, then reads the currently selected detail only if it is still registered. A
successful Unregister does not query the removed registration as part of that refresh.

Ordinary writes use `useMutation` with `retry: false` and `networkMode: "always"`.
Its pending state includes the refresh returned by `onSettled`, after either
success or failure. Read errors are shown separately without changing the write's
outcome. Ordinary writes include service/command operations, project registration,
worktree changes (confirmed remove/forget), env export and port updates. Their
completed mutation entries can be collected immediately when no longer observed.

The synchronous submission lock covers both mutations and direct secret writes,
including their refresh. Requests are never queued, persisted or retried
automatically. Secrets, Logs and previews stay outside the query/mutation cache;
secret request payloads are not retained there. Only the port update mutation
accepts a non-secret `value` field.
Logs and removal previews are explicit snapshot requests; polling, navigation,
focus changes and reloads do not replay them. Services and commands show server
results without optimistic state changes.

The header offers System (default), Light and Dark. The selection is stored in
local storage for the console origin (scheme, host and port); a new server port
has its own preference. If browser storage is unavailable, selection works for the
current page. Theme initialization runs before React mounts, using bundled code
without an inline script. System mode responds to OS appearance changes.

Keep palette changes in semantic tokens. Primary actions and selected navigation
use neutral contrast; reserve color for success, warning and error states. Muted
text must remain readable in tables, dialogs and both themes. Destructive controls
use a separate foreground token so text remains readable on their filled surface.

Hash routes keep direct links and reloads compatible with FastAPI's static-file
mount. The initial token fragment is consumed before the router mounts; subsequent
routes contain no credentials. List filters live in search parameters inside the
hash. Detail tabs use manual keyboard activation (arrow keys to focus, Enter/Space
to select), so focus does not create extra history entries.

Overview (`/dashboard`) is the entry route. `/environments` retains the complete
list and existing deep links; project selection, filters and eight-row pagination
are URL state. The tree remains mounted while the right-hand page changes, and
desktop/mobile menus share search and expanded projects. Plus buttons open the
existing form workflow through a create/attach choice. The dashboard derives
its snapshot from the existing overview query; it adds no writes or telemetry.
Service bars use SVG attributes and bundled CSS, preserving the strict CSP.

Project source details and the environment list share `/environments?project=ID`.
`/projects/:id` redirects there; no separate information component or dropdown menu
is needed. Project names are links, chevrons toggle the tree, and overflow results
use Show all. Normal rows omit the redundant worktree type; unavailable directories
keep a short status. Optional form configuration and secret usage/storage guidance
use native disclosures. Follow the [shared terminology](../../docs/management.md#terminology):
an Environment is the taskenv registration and a worktree is the Git directory.

The shadcn dialog keeps Radix focus trapping and portals, with a static overlay
and CSS scroll lock instead of Radix's injected scroll-lock stylesheet. This
preserves the server's `style-src 'self'` policy. Preserve this local adaptation
when updating generated components. Fonts, icons and all other assets are bundled.

Browser tests include a real CLI/server lifecycle and isolated mocked records for
multi-project navigation and layout. Screenshots are written to `test-results/`.
