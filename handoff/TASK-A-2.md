# TASK A-2 — `Result` + runner result-event emission

**Builder:** Cursor. **Product code only.** Do NOT modify, add, or delete anything under `tests/`
(including `tests/stubs/`), `docs/`, or `handoff/`. The reviewer contract (`tests/sdk/test_result.py`)
and the stub `tests/stubs/returns_result/` are FROZEN — make them pass by changing product code.

Second increment of **Stage A**. Introduces the `Result` a workflow's `run()` returns (SDK §3.3) and
teaches the SDK runner to turn a returned `Result` into the `result` event the chassis already records —
with the video path made relative to the video folder (SDK §5.5). Everything a workflow needs to report a
finished video, without hand-emitting an event.

Files you may touch: `sdk/sfvf/result.py` (new), `sdk/sfvf/__init__.py`, `sdk/sfvf/runner.py`, and
`app/core/supervisor.py` (see §4). Do not add dependencies.

## 1. `sdk/sfvf/result.py` (new) — the `Result` type

A dataclass with the fields of SDK §3.3:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class Result:
    video: Path
    caption: str | None = None
    hashtags: list[str] | None = None
    cover_frame_s: float = 1.0
    notes: str | None = None
    extra: dict[str, Any] | None = None
```

(`video` is required and first; the rest are optional with the defaults shown — `cover_frame_s` defaults
to `1.0`.)

## 2. `sdk/sfvf/__init__.py` — export it

Add `Result` to the imports and to `__all__`, alongside the existing `Context`/`ContextFile`/`ContextPaths`.

## 3. `sdk/sfvf/runner.py` — emit a `result` event from a returned `Result`

The video entrypoint runs without a `--result` file (the supervisor passes none): its finished video is
reported through an emitted `result` event, which the supervisor already parses. So when the entry
function returns a `Result`, emit one `result` event and do **not** also try to write it to a result file.

In `_run`, after the entry call (you already hold the constructed `ctx`), branch on the return:

```python
    if isinstance(returned, Result):
        emit(_result_event(returned, ctx))
    elif result_path is not None:
        _write_result(result_path, _capture_return(returned))
```

- Keep the existing `result_path` path for `prepare` (which returns a dict / None) exactly as-is; only the
  `Result` case is new.
- `_result_event(result, ctx)` builds `{"t": "result", ...}` with:
  - `"video"`: the `result.video` path **relative to `ctx.paths.video`**, as a POSIX string (forward
    slashes) — but **normalise (`resolve()`) before the containment check**, so a `..` component cannot
    slip a path out of the folder while still passing a *lexical* `is_relative_to`. Concretely: let
    `root = ctx.paths.video.resolve()`; let `candidate = result.video if result.video.is_absolute() else
    root / result.video`; `resolved = candidate.resolve()`. If `resolved.is_relative_to(root)`, emit
    `resolved.relative_to(root).as_posix()`; otherwise fall back to `str(resolved)` (an absolute path)
    rather than raising or emitting an escaping `"../…"` string. This mirrors the project's resolve-then-
    confine path standard (SDK-1 cache restore; the file-server `safe_join`).
  - `"cover_frame_s"`: always included (it has a default).
  - `"caption"`, `"hashtags"`, `"notes"`, `"extra"`: included only when not `None` (omit a `None` field
    rather than emitting `null`).
- Use the existing `emit` (already imported in `runner.py`).

Backward compatibility: a workflow that returns `None` (and emits its own `result` event, as the existing
stubs do) must behave exactly as before — no `Result`, no new emission.

## 4. `app/core/supervisor.py` — persist the whole Result, not just video/caption

The runner emits every Result field in the `result` event, but the supervisor currently keeps only two of
them when it records the video:

```python
            if event.get("t") == "result":
                captured = {key: event[key] for key in ("video", "caption") if key in event}
```

This drops `hashtags`, `cover_frame_s`, `notes`, and `extra` from `video.json` — but SDK §3.3 records
`extra` verbatim and displays `notes`, and sequence continuity (`ctx.previous`) reads a prior video's
`Result.extra`, so the whole Result must survive. Widen the capture to retain every field of the result
event except its type tag:

```python
            if event.get("t") == "result":
                captured = {key: value for key, value in event.items() if key != "t"}
```

`VideoRecord.result` is already a free-form `dict[str, Any] | None`, so no record-schema change is needed.
This stays backward compatible: a workflow (or existing stub) that emits only `video`/`caption` still yields
exactly `{"video": ..., "caption": ...}`.

## Acceptance (the frozen contract)

Two frozen test files:
- `tests/sdk/test_result.py` — the runner side (below).
- `tests/core/test_result_persistence.py` — the supervisor side: running `tests/stubs/returns_result`
  through `run_request` (dry-run) yields `video.json` whose `result` is the **whole** Result:
  `{"video": "artifacts/final.mp4", "caption": "hi", "hashtags": ["a", "b"], "cover_frame_s": 1.0,
  "notes": "n", "extra": {"k": 1}}`.

### `tests/sdk/test_result.py`

- `Result` field defaults: `caption`/`hashtags`/`notes`/`extra` default `None`, `cover_frame_s` defaults
  `1.0`; all fields carry through when set.
- Running `tests/stubs/returns_result` through `runner._run` (entrypoint, `result_path=None`) emits exactly
  one `result` event with `video == "artifacts/final.mp4"` (video-relative, POSIX), `caption == "hi"`,
  `hashtags == ["a", "b"]`, `notes == "n"`, `extra == {"k": 1}`, `cover_frame_s == 1.0`.

## Full local gate (all six must pass — run from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```

Do not weaken, skip, or edit any test to make the gate pass. Existing runner/supervisor tests (stubs that
return `None` and emit their own result event) must still pass unchanged.
