from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Any

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def kill_tree(proc: subprocess.Popen[Any]) -> None:
    """Kill a subprocess and its descendants. No-op if it has already exited."""
    if proc.poll() is not None:
        return
    pid = proc.pid
    if pid is None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
                timeout=15,
                creationflags=_NO_WINDOW,
            )
        else:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
