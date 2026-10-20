"""Per-service supervisor. Owns its child and authenticated loopback control socket.

Started only for an explicitly requested service; no global daemon or restart policy.
Input (including secrets) arrives over an anonymous pipe and is never persisted.
"""

from __future__ import annotations

import hmac
import json
import os
import selectors
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from lodex_core.management.common import now, write_private
from lodex_core.management.environment import LogRedactor
from lodex_core.management.processes import (
    STOP_GRACE_SECONDS,
    exited_without_reaping,
    signal_group,
)


def supervise(payload: dict[str, Any]) -> None:
    directory = Path(payload["directory"])
    status: dict[str, Any] = {"state": "starting", "observed_at": now(), "exit_code": None}
    token = payload["token"]
    redactor = LogRedactor(payload["secrets"])
    child: subprocess.Popen[bytes] | None = None
    requested_stop = False
    stop_deadline: float | None = None
    final_state = "stopped"

    def save() -> None:
        status["observed_at"] = now()
        write_private(directory / "status.json", json.dumps(status))

    def begin_stop(state: str) -> None:
        nonlocal stop_deadline, final_state
        if stop_deadline is None:
            if child is not None:
                signal_group(child, signal.SIGTERM)
            stop_deadline = time.monotonic() + STOP_GRACE_SECONDS
            final_state = state
            status["state"] = "stopping"
            save()

    def interrupted(signum: int, frame: object) -> None:
        nonlocal requested_stop
        requested_stop = True

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    with socket.socket() as server, selectors.DefaultSelector() as selector:
        server.bind(("127.0.0.1", 0))
        server.listen(4)
        server.setblocking(False)
        write_private(
            directory / "control.json",
            json.dumps(
                {
                    "port": server.getsockname()[1],
                    "token": token,
                }
            ),
        )
        selector.register(server, selectors.EVENT_READ, "control")
        fd = os.open(directory / "output.log", os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        with os.fdopen(fd, "wb", buffering=0) as log:
            try:
                child = subprocess.Popen(
                    payload["argv"],
                    cwd=payload["cwd"],
                    env=payload["env"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                assert child.stdout is not None
                os.set_blocking(child.stdout.fileno(), False)
                selector.register(child.stdout, selectors.EVENT_READ, "log")
                status["pid"] = child.pid
                ready_port = payload.get("ready_port")
                deadline = time.monotonic() + payload["ready_timeout"]
                ready_after = time.monotonic() + 0.15
                save()
                while True:
                    for key, _ in selector.select(timeout=0.05):
                        if key.data == "log":
                            data = os.read(child.stdout.fileno(), 8192)
                            if data:
                                log.write(redactor.feed(data))
                            else:
                                selector.unregister(child.stdout)
                        else:
                            connection, _ = server.accept()
                            with connection:
                                connection.settimeout(0.25)
                                try:
                                    request = json.loads(connection.recv(4096))
                                    if not hmac.compare_digest(
                                        str(request.get("token", "")), token
                                    ):
                                        continue
                                    if request.get("action") == "stop":
                                        requested_stop = True
                                    connection.sendall(json.dumps(status).encode())
                                except (OSError, ValueError):
                                    pass
                    if requested_stop:
                        begin_stop("stopped")
                    elif stop_deadline is None and exited_without_reaping(child.pid):
                        begin_stop("failed" if status["state"] == "starting" else "exited")
                    elif status["state"] == "starting":
                        ready = ready_port is None and time.monotonic() >= ready_after
                        if ready_port is not None:
                            try:
                                with socket.create_connection(
                                    ("127.0.0.1", ready_port), timeout=0.1
                                ):
                                    ready = True
                            except OSError:
                                pass
                        if ready:
                            status["state"] = "running"
                            save()
                        elif time.monotonic() >= deadline:
                            status["error"] = "readiness_timeout"
                            begin_stop("failed")
                    if stop_deadline is not None and time.monotonic() >= stop_deadline:
                        # Grant the whole group its grace period, not only the leader.
                        # Keep serving control requests and draining logs during it.
                        signal_group(child, signal.SIGKILL)
                        status["exit_code"] = child.wait()
                        status["state"] = final_state
                        # Bounded drain: a repo child may have inherited stdout.
                        while True:
                            try:
                                data = os.read(child.stdout.fileno(), 8192)
                            except BlockingIOError:
                                break
                            if not data:
                                break
                            log.write(redactor.feed(data))
                        break
            except Exception:
                status.update(state="unknown", error="service_cleanup_failed")
                if child is not None:
                    signal_group(child, signal.SIGKILL)
                    status["exit_code"] = child.wait()
                status["state"] = "failed"
                status["error"] = "service_launch_failed"
            finally:
                if child is not None and child.stdout is not None:
                    child.stdout.close()
                log.write(redactor.feed(b"", final=True))
                save()


def main() -> None:
    payload = json.load(sys.stdin)
    supervise(payload)


if __name__ == "__main__":
    main()
