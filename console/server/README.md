# Console server

The `lodex-console` distribution provides `lodex_console`, depending on
`lodex-core`, FastAPI and Uvicorn. It does not depend on the CLI.

- `src/lodex_console/app.py`: loopback HTTP access, API routes and asset serving.
- `actions.py`: request validation, dispatch and UI queries over Core.
- `worker.py`: per-request subprocess, with requests passed through private stdin.
- `static/`: generated frontend assets, included in wheel and source distribution.
- `tests/`: HTTP access control, action validation and management integration.

Run `uv run pytest console/server/tests` from the repository root. The
`console/tests` suite additionally checks CLI launch, server shutdown and service
survival. Installed use requires no Node.js runtime.

Building from the workspace rebuilds the frontend first. Run
`pnpm --dir console/f2e install --frozen-lockfile` before a release build.
Building a wheel from the
server's source distribution uses its already bundled assets.
