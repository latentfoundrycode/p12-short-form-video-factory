# TASK B-2 — `media.edit.trim` + `media.edit.cut` on real Kinocut

**Builder:** Cursor. **Product code only.** Do NOT modify, add, or delete anything under `tests/`,
`docs/`, `handoff/`, `requirements*.txt`, `mypy.ini`, or `sdk/pyproject.toml` — the frozen reviewer contract
`tests/integration/test_edit.py` and all config/deps are already in place. Make the contract pass by writing
product code.

Create the `media.edit` submodule backing SFVF's §6.6 edit surface with the **real Kinocut** programmatic
`Client`. Kinocut is local/free and FFmpeg-backed (no account, no key, nothing uploaded), so per SDK §10 it
runs **REAL in both dry and non-dry modes** — `dry_run` means "no paid spend", not "no editing". Scope for
this increment is **`trim` and `cut` only**; `mix`/duck (§6.6) is deferred and must NOT be added.

## Files you may touch

- **`sdk/sfvf/media/edit.py`** (new) — the adapter.
- **`sdk/sfvf/media/__init__.py`** — add `edit` to the imports and `__all__` (it currently exports
  `finalize`, `graphics`, `speech`).

Do not touch `graphics.py`, `speech.py`, `finalize.py`, or anything else.

## The surface (§6.6)

```python
trim(video, start, end) -> str
cut(clips, *, transitions=None) -> str
```

- `trim(video: str, start: float, end: float) -> str` — trim `video` to the `[start, end)` window (seconds).
- `cut(clips: list[str], *, transitions: list[str] | None = None) -> str` — concatenate `clips` in order,
  with optional per-pair `transitions`.
- **Return a video-relative POSIX path string** (NOT a `Path`, NOT absolute), exactly like
  `graphics.render` — see §5.5: file outputs are video-relative strings the JSON step cache content-addresses.
  The spec shows `-> Path` for these not-yet-built functions; the established SFVF convention (A-3..A-5,
  B-1b) is the video-relative **string**, and the frozen test asserts a relative `str`.

## How to build it (follow the `graphics.render` conventions already in `graphics.py`)

Reuse the same patterns `graphics.py` established — read them there and mirror them:

1. **Ambient context:** `ctx = current_context()` (from `sfvf._runtime`) **directly** at the top of each
   function — exactly as `graphics.render` does — so a call with no active context raises the SDK-standard
   `RuntimeError` (the frozen `test_edit_requires_active_context` asserts `RuntimeError`, matching
   graphics/agents/finalize). Do NOT wrap or convert that exception. Do NOT gate on `ctx.dry_run` — edit runs
   real in both modes.
2. **Resolve inputs:** the `video`/`clips` arguments are **video-relative** path strings. Resolve each against
   `ctx.paths.video` to an absolute path before handing it to Kinocut (`(ctx.paths.video / rel).resolve()`).
   You may assume they exist; if a resolved input is missing, a clear error is fine.
3. **Deterministic output name (content-addressed):** build the output filename from the inputs with the
   existing `_sha8(...)` helper pattern from `graphics.py` (`hashlib.sha256(json.dumps(payload,
   sort_keys=True)).hexdigest()[:8]`). Use:
   - `trim`: `_sha8([video, start, end])` → `f"edit-trim-{sha}.mp4"`
   - `cut`: `_sha8([clips, transitions])` → `f"edit-cut-{sha}.mp4"`
   Place the output under `ctx.paths.artifacts` (mkdir parents) and return it **relative to
   `ctx.paths.video`** as POSIX (mirror `graphics.py`'s `_artifact(ctx, filename)` helper — you may import/reuse
   it if it is module-private there, or replicate the same three lines). The frozen determinism test requires
   the same `(inputs)` to yield the same relative path across different video folders.
4. **Call Kinocut** via its programmatic `Client` (import **lazily inside the adapter**, not at module top, so
   the SDK imports without the optional `kinocut` package installed):

   ```python
   try:
       from kinocut import Client
   except ImportError as exc:  # optional `sfvf[edit]` extra
       raise RuntimeError(
           "media.edit requires the 'kinocut' package. Install the SDK 'edit' extra: "
           "pip install 'sfvf[edit]' (or pip install kinocut==1.15.1)."
       ) from exc
   ```

   The `Client` API is **verified against the pinned 1.15.1** (methods return a pydantic `EditResult` whose
   `.output_path` is the written file):

   - **trim:** `Client().trim(input: str, start: float | str = 0, duration=None, end: float | str | None = None,
     output: str | None = None, accurate: bool = False) -> EditResult`.
     Call `Client().trim(abs_in, start=start, end=end, output=abs_out)`; the SFVF `end` maps to Kinocut's
     `end=` (do NOT pass `duration`). Read `.output_path`.
   - **cut:** `Client().merge(clips: list[str], output: str | None = None, transitions: list[str] | None =
     None, transition_duration: float = 1.0) -> EditResult`.
     Call `Client().merge(abs_clips, transitions=transitions, output=abs_out)`. Read `.output_path`.

   Pass **absolute** paths for both inputs and `output=` so Kinocut's cwd is irrelevant. Construct `Client()`
   per call (cheap) or once at module scope inside the lazy block — your choice; keep it simple and typed.
5. **Types / mypy:** the project is `strict`. `kinocut` has no stubs but `mypy.ini` already ignores missing
   imports for `kinocut.*`. Annotate the public functions exactly as the signatures above. `EditResult` is
   untyped to mypy — read `.output_path` and coerce to what you need without `# type: ignore` if possible; if
   the value is `Any`, wrap in `str(...)` / `Path(...)` as appropriate.

## Acceptance — `tests/integration/test_edit.py` (frozen; installed + passing locally is required)

- `test_trim_produces_shorter_clip` — a 3s clip trimmed to `[0,1]` yields a valid ~1s MP4 at a relative path.
- `test_cut_concatenates_clips_in_order` — red(1s)+blue(1s) concatenate to a ~2s clip; a frame at 0.3s is red
  and at 1.7s is blue (proves real, ordered concat).
- `test_edit_runs_in_non_dry_mode` — trim works with `dry_run=False`.
- `test_edit_output_is_video_relative` — output is a POSIX relative path resolving under `ctx.paths.video`.
- `test_trim_is_deterministic_across_video_folders` — same inputs → same relative path across two folders.
- `test_edit_requires_active_context` — calling with no active context raises `LookupError`.

Do not weaken, skip, or edit any test.

## Full local gate (from the worktree venv; kinocut + ffmpeg are installed)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```

Confirm the six `tests/integration/test_edit.py` tests RAN (not skipped) and passed, and the rest of the suite
stays green.
