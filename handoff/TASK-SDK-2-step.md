# TASK-SDK-2 — `ctx.step`, the cached step boundary

## REVISION 1 — returned file paths are VIDEO-relative (SDK §5.5), not artifacts-relative
Cross-family review caught that the first implementation (and the original test) treated returned
file paths as relative to `ctx.artifacts`, but SDK §5.5 states they are **relative to the video
folder**: files are written under `ctx.artifacts` (i.e. `video/artifacts/…`) and returned as e.g.
`"artifacts/final.mp4"`. Fix the file handling in `ctx.step` accordingly:
- Derive the files-to-store by walking `value` for strings that name a path **relative to
  `self.paths.video`** (not `artifacts`) which exists as a file.
- Restore with `StepCache.get(key, restore_into=self.paths.video)` (not `artifacts`), so a cached
  result recreates files at their video-relative location.
The updated test `test_step_stores_and_restores_returned_files_video_relative` covers this (it writes
`video/artifacts/final.mp4`, returns `"artifacts/final.mp4"`, and asserts restore recreates it under
the video folder). Everything else about `ctx.step` was correct and both reviewers verified it — keep it.
Change only `sdk/sfvf/context.py`; do not modify the tests. Original brief below.

---


## One-line task and why
Add `ctx.step(...)` — the step boundary that consults the SDK-1 cache, returns a cached result
instantly (body not run), otherwise runs the body and stores the result, and records a `step` event.
This is the unit every meaningful piece of workflow work is wrapped in. Workflow SDK §4.5, §5.1-§5.5.
Second increment of the SDK/step-mechanism stage. SDK-only (`sdk/sfvf/context.py`); it uses the
already-merged `sfvf.cache` (`step_key`, `StepCache`).

## The failing reviewer test to make pass (already written — DO NOT modify it)
`tests/sdk/test_step.py` (6 tests) fails on `main`. It is the contract. Make it pass by implementing
the code; do not edit/weaken the test.

## What to implement in `sdk/sfvf/context.py`

### Context fields (optional, so existing `context.json` still validates)
- Add to `ContextPaths`: `cache: Path | None = None` (the content-addressed cache root).
- Add to `ContextFile`: `workflow_version: str = "0"`.
- These are OPTIONAL with defaults — the supervisor does not populate them yet (that is SDK-2b), so
  existing `context.json` files and the supervisor tests must keep validating unchanged.
- The `ContextFile` docstring currently says "fixed boundary contract; Stage 3 extends behaviour, not
  this shape." Update it: the SDK stage extends the context's content (per Architecture §3.2, the
  context carries everything the workflow needs to begin); the JSON-file boundary mechanism is what is
  stable. Keep it accurate and brief.

### `Context` accessors
- Expose `self.workflow_version` (from the file).
- Expose `self.artifacts` (= `file.paths.artifacts`) as a convenience — the test uses `ctx.artifacts`.
  (Leave the other §4.1 identity accessors — workflow_id, run_id, video_index, video_count, dry_run,
  step_concurrency — for a later increment; do not add them here.)

### `Context.step(family, *, inputs, label=None)` → a context manager
Returns an object usable as `with ctx.step(...) as step:` exposing `step.cached` (bool),
`step.value`, and `step.set(value)`. Semantics:
- On enter: compute `key = step_key(self.workflow_version, family, inputs)` (from `sfvf.cache`). Build
  `StepCache(self.paths.cache)` and call `get(key, restore_into=self.paths.artifacts)`. If it returns a
  value → `step.cached = True`, `step.value = <that value>` (files already restored into artifacts by
  the cache). Else → `step.cached = False`, `step.value = None`.
- `step.set(value)` records the result to store (JSON-serializable).
- On exit:
  - If the `with` body raised, propagate it and store NOTHING (a failed step must not be cached).
  - If it was a cache hit: emit a `step` event with `status="cached"`.
  - If it was a miss and `set(...)` was called: DERIVE the files to store — walk `value` recursively
    (dicts/lists) for string values that name a path **relative to `self.paths.artifacts` which exists
    as a file**, collect them as `{relative_name: artifacts/relative_name}`, then
    `StepCache(...).put(key, value, files=that_map)`; emit a `step` event with `status="ok"`.
    (SDK-1's `put` already refuses unsafe names and stores by content; `get` restores by content.)
- The `step` event shape (Workflow SDK §3.3 / Architecture §3.3): emit via the existing `emit()` /
  `self.emit(...)` — `{"t": "step", "name": <family>, "key": <short>, "label": <label or family>,
  "status": "cached" | "ok"}`, where `<short>` is a short prefix of the full key (e.g. its first 12
  hex chars). `label` is display-only and MUST NOT be part of the cache key.
- If `self.paths.cache is None`, raise a clear error (real runs always provide it; the tests do).

Also support the raise-safety and label-independence the tests assert.

## Scope — files you may change
- `sdk/sfvf/context.py` only.

## Do NOT touch
- `tests/**` (make the reviewer test pass by implementing), `app/` (the supervisor wiring is a
  separate later increment), `sdk/sfvf/cache.py` (use it as-is), `sdk/sfvf/runner.py`, the frontend,
  `.github/`, `docs/`, `handoff/`. No dependencies. Do not weaken any test or CI.

## Acceptance
- `tests/sdk/test_step.py` passes; all existing tests still pass (the supervisor's `context.json` must
  still validate — the new fields are optional).
- Full six-command gate green. `sdk/sfvf/context.py` is under mypy strict scope — annotate fully.

## Gate — run all six before committing (worktree root, PowerShell)
```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```

## Commit message (house style)
```
Add ctx.step, the cached step boundary that returns a stored result without re-running the body and records each step, so workflow work reuses correctly and appears in the record.
```
(Cursor appends its `Co-authored-by` trailer automatically.)

## Report back
Print the files changed, the commit hash, and the final pytest count.
