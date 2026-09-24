# TASK-h63 — bounded hard timeout for FFmpeg subprocess ops

## Goal

Close H63. `_ffmpeg._run` runs FFmpeg/ffprobe via `subprocess.run` with no `timeout=`. Since H6, `finalize`'s encode and `media.edit.trim`/`cut` emit heartbeats while FFmpeg runs, so the 300 s silence watchdog no longer kills them — which means a GENUINELY hung/deadlocked FFmpeg op now has no backstop at all (it emits no cost events either, so the budget guard never fires) and would run forever. Give `_run` a finite default timeout so every FFmpeg/ffprobe call inherits a hard backstop, while a legitimately long encode (well under the cap) still completes.

## The one file to change

`sdk/sfvf/_ffmpeg.py` only. Do not touch any test or any other module. Frozen contract: `tests/sdk/test_ffmpeg_timeout.py`.

## Current code

```python
def _run(command: list[str], *, capture_stderr: bool = False) -> str:
    try:
        completed = subprocess.run(  # noqa: S603
            command, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        raise RuntimeError(f"command failed: {command}\n{stderr}") from exc
    except OSError as exc:
        raise RuntimeError(f"command failed: {command}\n{exc}") from exc
    ...
```

## The change

1. Add a module-level constant `_DEFAULT_TIMEOUT_S: float = 3600.0` (a generous one-hour backstop: it never false-kills a legitimate local encode on a single-user app, but bounds a true hang). Place it near the top of the module.
2. Add a keyword-only parameter `timeout: float = _DEFAULT_TIMEOUT_S` to `_run`, and pass `timeout=timeout` to `subprocess.run`. (`subprocess.run` kills the child and waits when the timeout expires, so no orphan is left.)
3. Catch `subprocess.TimeoutExpired` and raise a clear `RuntimeError` whose message contains the word `timed out`, the timeout value, and the command — e.g. `raise RuntimeError(f"command timed out after {timeout}s: {command}") from exc`. Put this `except` before the `OSError` handler (order the excepts so `TimeoutExpired` is caught explicitly; note `TimeoutExpired` is a subclass of `SubprocessError`, not `OSError`, so ordering is not strictly required, but keep it explicit and above `OSError`).

That is the whole change — every existing caller (`finalize`, `media.edit`, the probe/silent-audio helpers) inherits the default backstop with no signature change on their side.

## Constraints

- Behaviour-preserving for the normal path: a fast command still returns its stdout exactly as today. The default timeout is generous enough not to affect any real encode.
- No new dependency (`subprocess` is already imported). No change to `_run`'s return contract or to `capture_stderr`.
- One paragraph is one line in any Markdown you write (no hard wraps).

## Done when

- `tests/sdk/test_ffmpeg_timeout.py` is fully green (it fails to import now — `_DEFAULT_TIMEOUT_S` is the new symbol).
- The finalize/edit suites stay green: `tests/sdk/test_finalize.py`, `tests/sdk/test_edit_heartbeat.py`, `tests/integration/test_edit.py` (and any other `_ffmpeg` user).
- Full suite passes: `.\.venv\Scripts\python.exe -m pytest -q`.
- Gate clean: `.\.venv\Scripts\python.exe -m ruff check .`, `-m ruff format --check .`, `-m mypy`.

## Builder notes

Record any tooling friction in `docs/BUILDER_NOTES.md` for Bridge Feedback; record any defect/pitfall learning there too, for the Issues file.
