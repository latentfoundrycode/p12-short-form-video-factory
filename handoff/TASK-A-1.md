# TASK A-1 — Ambient context bridge + FFmpeg stub-generation core + `ctx.params`

**Builder:** Cursor. **Product code only.** Do NOT modify, add, or delete anything under `tests/`
(including `tests/stubs/`), `docs/`, or `handoff/`. The reviewer contract
(`tests/sdk/test_runtime.py`, `tests/sdk/test_ffmpeg.py`) and the stub `tests/stubs/uses_runtime/`
are FROZEN — make them pass by changing product code.

This is the first increment of **Stage A** (the provided-functions dry-run stub layer + an example
workflow, arch build-order step 4 + the deferred "dry-run stubs" of step 3). It builds the two
foundations every later Stage-A increment needs: an **ambient handle on the active `Context`** (so
`sfvf.agents` / `sfvf.media.*` can reach `ctx.dry_run` and `ctx.paths` without being passed `ctx`), and
the **FFmpeg primitives** the dry-run stubs generate assets with (arch §2.1a, SDK §10). It also adds the
SDK-facing `ctx.params` accessor and makes FFmpeg available in CI.

Files you may touch: `sdk/sfvf/_runtime.py` (new), `sdk/sfvf/_ffmpeg.py` (new), `sdk/sfvf/runner.py`,
`sdk/sfvf/context.py`, and `.github/workflows/ci.yml`. Do not add Python dependencies (FFmpeg is an
external binary, installed via the CI step below and already present locally).

## 1. `sdk/sfvf/_runtime.py` (new) — the ambient-context bridge

A `contextvars`-based holder for the Context that is currently executing. Exact API (the contract
imports these three names):

```python
from __future__ import annotations
import contextvars
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import Context

_active: contextvars.ContextVar[Context | None] = contextvars.ContextVar(
    "sfvf_active_context", default=None
)

def set_active(ctx: Context) -> contextvars.Token[Context | None]:
    return _active.set(ctx)

def reset_active(token: contextvars.Token[Context | None]) -> None:
    _active.reset(token)

def current_context() -> Context:
    ctx = _active.get()
    if ctx is None:
        raise RuntimeError(
            "no active sfvf Context; provided functions may only be called inside a running workflow"
        )
    return ctx
```

Nesting must work (a second `set_active` shadows the first; `reset_active` on its token restores the
first) — `contextvars` gives this for free via the returned token.

## 2. `sdk/sfvf/runner.py` — publish the Context around the entrypoint

In `_run`, construct the `Context` once, publish it with `set_active` **before** calling the entry
function, and clear it with `reset_active` in a `finally` so it is cleared even when the entry raises.
Today the call is:

```python
    try:
        returned = func(Context(data))
    except Exception as exc:
        raise _EntryFailedError(f"{entry} failed: {exc}", traceback.format_exc()) from exc
```

Change it to construct `ctx = Context(data)` once, `token = set_active(ctx)`, then the existing
`try/except` around `func(ctx)`, with `reset_active(token)` in a `finally`. Import `set_active` /
`reset_active` from `._runtime`.

## 3. `sdk/sfvf/context.py` — add `ctx.params`

The SDK contract exposes settings to workflows as `ctx.params` (SDK §4.2, §11.1: `ctx.params["topic"]`).
In `Context.__init__`, add `self.params = file.settings` (keep the existing `self.settings` as-is).

## 4. `sdk/sfvf/_ffmpeg.py` (new) — FFmpeg/ffprobe primitives

Deterministic placeholder-asset generation and probing, via the `ffmpeg`/`ffprobe` binaries (subprocess).
Exact API (the contract calls these):

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass
class MediaProbe:
    duration_s: float
    width: int | None
    height: int | None
    has_audio: bool

def ffmpeg_available() -> bool: ...
def silent_audio(dest: Path, *, duration_s: float) -> Path: ...
def color_bars(dest: Path, *, duration_s: float, width: int, height: int, fps: int) -> Path: ...
def solid_image(dest: Path, *, width: int, height: int, color: str = "gray") -> Path: ...
def probe(path: Path) -> MediaProbe: ...
```

Implementation notes:
- `ffmpeg_available()` → both `ffmpeg` and `ffprobe` resolvable on PATH (`shutil.which`).
- Each generator creates parent dirs, overwrites (`-y`), returns `dest`, and produces **deterministic**
  output (no timestamps / RNG). Suggested lavfi sources: `silent_audio` → `anullsrc` (AAC in the dest
  container, e.g. `.m4a`), audio-only; `color_bars` → `smptebars=size=WxH:rate=<fps>` for `duration_s`,
  `-pix_fmt yuv420p -c:v libx264`, **video-only (no audio track)**; `solid_image` → `color=c=<color>:s=WxH`,
  one frame.
- `probe()` shells `ffprobe -v quiet -print_format json -show_format -show_streams` and parses:
  `duration_s` from `format.duration`; `width`/`height` from the first video stream (else `None`);
  `has_audio` true iff any stream has `codec_type == "audio"`.
- On a failed subprocess call, raise a `RuntimeError` that includes the command and captured stderr, so a
  broken FFmpeg invocation is diagnosable rather than silent.

These are internal (underscore-prefixed) modules — do **not** add them to `sdk/sfvf/__init__.py`'s public
`__all__`. The contract imports them by path (`from sfvf import _ffmpeg`, `from sfvf._runtime import ...`).

## 5. `.github/workflows/ci.yml` — make FFmpeg available on the runner

The stub engine shells out to FFmpeg, so the gate runner needs it. Add a setup step (with an `id`, e.g.
`deps_ffmpeg`) that installs FFmpeg on `windows-latest` via Chocolatey — `choco install ffmpeg -y
--no-progress` — placed among the other install steps (after the dependency installs, before the check
steps). Then extend the `if:` guard on **all six** check steps to also require
`steps.deps_ffmpeg.conclusion == 'success'`, so a failed FFmpeg install hard-stops the job exactly as a
failed pip/npm install does (keeping the existing "a setup failure skips every check" invariant). Do not
change anything else in the workflow (permissions, concurrency, caching, the checks themselves).

## Acceptance (the frozen contract)

- `tests/sdk/test_runtime.py`: `current_context()` raises when unset; `set_active`/`reset_active`
  publish/restore and nest; `ctx.params` equals the settings dict; and — via `tests/stubs/uses_runtime`
  run through `runner._run` — the active Context is `is`-identical to the `ctx` passed to the entrypoint
  during the call and is cleared afterwards.
- `tests/sdk/test_ffmpeg.py`: `ffmpeg_available()` is true; `silent_audio`/`color_bars`/`solid_image`
  produce valid files whose probed duration (±0.15s) and resolution match the request; `color_bars` has
  no audio track while `silent_audio` does.

## Full local gate (all six must pass — run from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```

Do not weaken, skip, or edit any test to make the gate pass.
