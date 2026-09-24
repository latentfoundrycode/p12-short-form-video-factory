"""H63 contract: FFmpeg subprocess ops have a bounded hard timeout (render robustness).

H6 made `finalize`'s encode and `media.edit.trim`/`cut` emit heartbeats while FFmpeg runs, so the
§2.8 300 s silence watchdog no longer kills a legitimately long encode. The side effect: a GENUINELY
hung/deadlocked FFmpeg op had no backstop at all — `_ffmpeg._run` used `subprocess.run` with no
`timeout=`, emits no cost events (so the budget guard never fires), and would run forever. This adds
a finite default timeout to `_run` so every FFmpeg/ffprobe call inherits a hard backstop, while a
real long encode (well under the cap) still completes. A timeout kills the child and raises a clear
error. The command is a local python sleep — no ffmpeg, no network, no spend.
"""

from __future__ import annotations

import math
import sys
import time

import pytest
from sfvf._ffmpeg import _DEFAULT_TIMEOUT_S, _run


def test_default_timeout_is_finite_and_positive() -> None:
    # The backstop must be a real finite cap, not None/inf (else the "runs forever" hole returns).
    assert isinstance(_DEFAULT_TIMEOUT_S, int | float)
    assert math.isfinite(_DEFAULT_TIMEOUT_S)
    assert _DEFAULT_TIMEOUT_S > 0


def test_run_completes_normally_within_the_timeout() -> None:
    out = _run([sys.executable, "-c", "import sys; sys.stdout.write('hi')"])
    assert "hi" in out


def test_run_raises_and_returns_promptly_on_a_hang() -> None:
    # A command that would run for 6 s is aborted by a 0.5 s timeout: the call raises a clear error
    # well before the command's own runtime, proving the hard timeout fired (not that it waited).
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="timed out"):
        _run([sys.executable, "-c", "import time; time.sleep(6)"], timeout=0.5)
    assert time.monotonic() - start < 4.0  # aborted early, not after the full 6 s
