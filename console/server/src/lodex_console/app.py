"""Optional loopback console. Import only when explicitly launched."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import secrets
import socket
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from lodex_console.actions import Action, detail, overview
from lodex_core.management.common import ManagementError

STATIC = Path(__file__).parent / "static"


def error(code: str, message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code, "message": message}}, status)


def create_app(root: Path, token: str, port: int) -> FastAPI:
    host = f"127.0.0.1:{port}"
    origin = f"http://{host}"
    children: set[asyncio.subprocess.Process] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        for child in list(children):
            if child.returncode is None:
                child.terminate()
        for child in list(children):
            await child.wait()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def protect(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if (
            request.headers.get("host") != host
            or not request.client
            or request.client.host not in ("127.0.0.1", "::1", "testclient")
        ):
            return error("forbidden", "Loopback access required", 403)
        if request.url.path.startswith("/api/"):
            if not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {token}"):
                return error("unauthorized", "Open the URL printed by lodex console", 401)
            supplied_origin = request.headers.get("origin")
            if supplied_origin is not None and supplied_origin != origin:
                return error("forbidden", "Invalid request origin", 403)
            if request.method != "GET" and supplied_origin != origin:
                return error("forbidden", "Same-origin writes required", 403)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
                    "base-uri 'none'; form-action 'self'"
                ),
            }
        )
        return response

    @app.exception_handler(ManagementError)
    async def management_error(request: Request, exc: ManagementError) -> JSONResponse:
        return JSONResponse(
            {"ok": False, "error": exc.as_dict()}, 409 if exc.code == "busy" else 400
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error("invalid_input", "Invalid action fields", 422)

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return {"ok": True, "result": overview(root)}

    @app.get("/api/task/{target}")
    def task(target: str) -> dict[str, Any]:
        return {"ok": True, "result": detail(root, target)}

    @app.post("/api/action")
    async def action(request: Action) -> JSONResponse:
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "lodex_console.worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ, "LODEX_HOME": str(root)},
        )
        children.add(child)
        try:
            output, _ = await child.communicate(request.model_dump_json().encode())
            try:
                payload = json.loads(output)
            except ValueError:
                return error("unknown", "Caller interrupted; inspect state before retrying", 500)
            return JSONResponse(payload)
        except asyncio.CancelledError:
            if child.returncode is None:
                child.terminate()
                await child.wait()
            raise
        finally:
            children.discard(child)

    if STATIC.is_dir():
        app.mount("/", StaticFiles(directory=STATIC, html=True), name="console")
    return app


def serve(port: int) -> None:
    import uvicorn

    if not (STATIC / "index.html").is_file():
        raise ManagementError(
            "missing_assets", "Build console assets: pnpm --dir console/f2e run build"
        )
    root = Path(os.environ.get("LODEX_HOME", "~/.lodex")).expanduser().resolve()
    token = secrets.token_urlsafe(32)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", port))
        actual_port = listener.getsockname()[1]
        print(f"Lodex console: http://127.0.0.1:{actual_port}/#token={token}", flush=True)
        config = uvicorn.Config(
            create_app(root, token, actual_port),
            access_log=False,
            proxy_headers=False,
            timeout_graceful_shutdown=2,
        )
        uvicorn.Server(config).run(sockets=[listener])
