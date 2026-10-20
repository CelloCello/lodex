"""Process-group ownership shared by foreground commands and service supervisors."""

from __future__ import annotations

import ctypes as c
import os
import subprocess
import sys

STOP_GRACE_SECONDS = 3


class _DarwinSiginfo(c.Structure):
    # Layout from the macOS SDK's sys/signal.h (siginfo_t).
    _fields_ = [
        ("signo", c.c_int),
        ("errno", c.c_int),
        ("code", c.c_int),
        ("pid", c.c_int),
        ("uid", c.c_uint),
        ("status", c.c_int),
        ("addr", c.c_void_p),
        ("value", c.c_void_p),
        ("band", c.c_long),
        ("pad", c.c_ulong * 7),
    ]


_native_waitid = None
if sys.platform == "darwin" and not hasattr(os, "waitid"):
    _native_waitid = c.CDLL(None, use_errno=True).waitid
    _native_waitid.argtypes = [c.c_uint, c.c_uint, c.POINTER(_DarwinSiginfo), c.c_int]
    _native_waitid.restype = c.c_int


def exited_without_reaping(pid: int) -> bool:
    """Observe exit while retaining the child PID and process-group ownership."""
    options = os.WEXITED | os.WNOHANG | os.WNOWAIT
    waitid = getattr(os, "waitid", None)
    if waitid is not None:
        return waitid(os.P_PID, pid, options) is not None
    # Some macOS Python distributions omit os.waitid although libc supports it.
    if _native_waitid is None:
        raise RuntimeError("Process supervision requires waitid with WNOWAIT")
    info = _DarwinSiginfo()
    if _native_waitid(os.P_PID, pid, c.byref(info), options) != 0:
        error = c.get_errno()
        raise OSError(error, os.strerror(error))
    return bool(info.pid == pid)


def signal_group(child: subprocess.Popen[bytes], signum: int) -> None:
    """Signal an owned group before reaping its leader, including a zombie leader."""
    if child.returncode is not None:
        return
    # The unreaped leader pins the PGID against reuse by another job.
    try:
        os.killpg(child.pid, signum)
    except ProcessLookupError:
        pass
    except PermissionError:
        # Darwin returns EPERM for a group containing only zombies. A live member
        # with different credentials is a real failure, not a successful stop.
        if sys.platform != "darwin":
            raise
        members = subprocess.run(
            ["/bin/ps", "-g", str(child.pid), "-o", "stat="],
            capture_output=True,
            text=True,
            check=True,
            timeout=1,
        ).stdout.split()
        if not members or any(not member.startswith("Z") for member in members):
            raise
