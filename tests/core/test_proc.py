import subprocess
import sys
import time
from pathlib import Path

from app.core.proc import kill_tree


def _spawn_sleep() -> subprocess.Popen[str]:
    kwargs: dict[str, int | bool] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kwargs,  # type: ignore[arg-type]
    )


def test_kill_tree_terminates_a_live_child() -> None:
    proc = _spawn_sleep()
    try:
        assert proc.poll() is None
        time.sleep(0.1)
        kill_tree(proc)
        proc.wait(timeout=5)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_kill_tree_is_noop_on_exited_process(tmp_path: Path) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc.wait(timeout=5)
    assert proc.poll() is not None
    kill_tree(proc)
    assert proc.poll() is not None
