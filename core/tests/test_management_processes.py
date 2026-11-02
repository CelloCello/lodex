from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Any
from unittest.mock import Mock

import pytest

from lodex_core.management import processes

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS process-group behavior")


def test_owned_zombie_group_does_not_require_ps(monkeypatch: pytest.MonkeyPatch) -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    try:
        deadline = time.monotonic() + 3
        while not processes.exited_without_reaping(child.pid):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("Invoked ps"))
        processes.signal_group(child, signal.SIGKILL)
    finally:
        child.wait(timeout=3)


@pytest.mark.parametrize("count,first", [(0, 123), (-1, 123), (8, 123), (4, 456)])
def test_unknown_or_larger_groups_do_not_ignore_signal_permission_errors(
    monkeypatch: pytest.MonkeyPatch,
    count: int,
    first: int,
) -> None:
    child = Mock(pid=123, returncode=None)

    def reject(*_: Any) -> None:
        raise PermissionError("Signal denied")

    def members(_kind: int, pid: int, buffer: Any, _size: int) -> int:
        assert pid == child.pid
        buffer[0] = first
        return count

    monkeypatch.setattr(os, "killpg", reject)
    monkeypatch.setattr(processes, "exited_without_reaping", lambda _: True)
    monkeypatch.setattr(processes, "_native_listpids", members)
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: Mock(stdout="S\n"))
    with pytest.raises(PermissionError):
        processes.signal_group(child, signal.SIGKILL)
