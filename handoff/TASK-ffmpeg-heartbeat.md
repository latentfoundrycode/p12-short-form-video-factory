# TASK — heartbeat during blocking local FFmpeg ops (H6)

## Why
`finalize` (`_apply_house_format`) and `media.edit` (`trim`/`cut`) run FFmpeg synchronously with its
output captured (`_ffmpeg._run` uses `subprocess.run(capture_output=True)`; kinocut runs FFmpeg
internally). So during a long encode/concat the workflow subprocess produces NO stdout, and the
supervisor's §2.8 silence watchdog (300 s default) can kill a legitimately long op. Fix (one
consistent pass over both): a `heartbeat_during(...)` context manager that emits a `heartbeat` event
periodically from a daemon thread while the wrapped op runs, resetting the watchdog. `emit()` writes
to stdout under a module lock, so emitting from the helper thread is safe.

Frozen RED tests (committed, do not modify):
- `tests/sdk/test_emit.py` — `heartbeat_during` emits periodically while blocked, emits nothing for a
  fast op, and stops after the block exits.
- `tests/sdk/test_finalize.py::test_finalize_wraps_the_ffmpeg_encode_in_a_heartbeat`.
- `tests/sdk/test_edit.py::test_trim_wraps_the_ffmpeg_op_in_a_heartbeat`, `::test_cut_...`.

## Changes

### 1. `sdk/sfvf/emit.py` — the helper
Add a context manager (near `heartbeat`). It must accept the same identifiers `heartbeat` uses plus
`interval`:
```python
from contextlib import contextmanager
# (threading is already imported)

_HEARTBEAT_INTERVAL_S = 30.0  # < the 300 s silence watchdog, with a wide margin

@contextmanager
def heartbeat_during(
    name: str, *, waiting_on: str, interval: float = _HEARTBEAT_INTERVAL_S, key: str | None = None
) -> Iterator[None]:
    """Emit a `heartbeat` every `interval` seconds from a daemon thread until the block exits, so a
    long blocking local op (FFmpeg) keeps the supervisor's silence watchdog fed. The first heartbeat
    is one interval in, so an op faster than `interval` emits none. Never raises from the thread."""
    stop = threading.Event()

    def _loop() -> None:
        while not stop.wait(interval):
            heartbeat(name, waiting_on=waiting_on, key=key)

    thread = threading.Thread(target=_loop, name=f"sfvf-heartbeat-{name}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5.0)
```
Add `from collections.abc import Iterator` if not already imported. (`stop.wait(interval)` returns
False on timeout → emit; True when set → exit, so the loop is prompt to stop.)

### 2. `sdk/sfvf/finalize.py` — wrap the encode
Import the helper (`from .emit import heartbeat_during`) and wrap ONLY the house-format encode in
`_apply_house_format` (the long op — the ffprobe/subtitle probes are fast and stay unwrapped):
```python
    command.extend(["-map_metadata", "-1", str(dest)])
    with heartbeat_during("finalize", waiting_on="ffmpeg"):
        _run(command)
```

### 3. `sdk/sfvf/media/edit.py` — wrap trim and cut
Import the helper (`from ..emit import heartbeat_during`) and wrap each kinocut op:
```python
def trim(video: str, start: float, end: float) -> str:
    ctx = current_context()
    dest, rel = _artifact(ctx, f"edit-trim-{_sha8([video, start, end])}.mp4")
    abs_in = str((ctx.paths.video / video).resolve())
    with heartbeat_during("edit", waiting_on="ffmpeg"):
        _client().trim(abs_in, start=start, end=end, output=str(dest))
    return rel

def cut(clips: list[str], *, transitions: list[str] | None = None) -> str:
    ctx = current_context()
    dest, rel = _artifact(ctx, f"edit-cut-{_sha8([clips, transitions])}.mp4")
    abs_clips = [str((ctx.paths.video / clip).resolve()) for clip in clips]
    with heartbeat_during("edit", waiting_on="ffmpeg"):
        _client().merge(abs_clips, transitions=transitions, output=str(dest))
    return rel
```
(The `heartbeat_during` name must be a module-level import in `finalize` and `edit` so the frozen
tests can monkeypatch `finalize.heartbeat_during` / `edit.heartbeat_during`.)

## Scope / do NOT
- Only `sdk/sfvf/emit.py`, `sdk/sfvf/finalize.py`, `sdk/sfvf/media/edit.py`. Do NOT change
  `_ffmpeg._run`, the ffprobe/subtitle probes, the composition self-review, any test, or any stub.
  No new dependencies (`threading`, `contextlib`, `collections.abc` are stdlib).

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/sdk/test_emit.py tests/sdk/test_edit.py -q` → all pass.
- `PYTHONPATH=sdk python -m pytest tests/sdk/test_finalize.py -q -k "heartbeat"` → passes.
- `ruff check sdk tests` and `ruff format --check sdk tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
  (Full `test_finalize.py` and `test_edit.py`/`test_graphics_render.py` drive the node/ffmpeg toolchain
  and are env-flaky on some Windows dev boxes — CI signal, not the local gate.)
