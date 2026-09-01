# TASK-SDK-3 — `ctx.map`, many steps of one family in parallel

## One-line task and why
Add `ctx.map(...)` — run many items of one step family concurrently, each a full cached step, results
returned in input order. An episode of sixty independent shots should not take sixty times one shot's
wall clock. Workflow SDK §4.7. Third increment of the SDK/step-mechanism stage; builds on the merged
`ctx.step` (SDK-2).

## The failing reviewer test to make pass (already written — DO NOT modify it)
`tests/sdk/test_map.py` (6 tests) fails on `main` (no `ctx.map`). It is the contract.

## What to implement

### `Context.map(family, items, *, inputs, fn, label=None, concurrency=1, on_error="raise")`
In `sdk/sfvf/context.py`:
- `items`: an iterable. `inputs`: callable `item -> dict` (the step inputs). `fn`: callable
  `item -> value` (the step body). `label`: optional callable `item -> str` (display; default to the
  family). `concurrency`: max items in flight. `on_error`: `"raise"` (default) or `"collect"`.
- **Every item is a full step** — run each through the EXISTING `ctx.step(family, inputs=inputs(item),
  label=<label(item) or family>)`: a hit returns the cached value (fn not called), a miss runs
  `fn(item)` and `step.set(...)` stores it. So caching, file handling, and the `step` event are all
  inherited from `ctx.step` unchanged — do not reimplement them.
- **Results in INPUT order**, regardless of completion order. Run with a
  `concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency))`; submit one task per item
  and gather results by input index (do not use `as_completed` for the return order).
- **`on_error="raise"`** (default): return `list` of the item values in input order; the first item
  that raises propagates its exception out of `ctx.map` (fail fast, like a sequential loop).
- **`on_error="collect"`**: return `list[Outcome]` in input order; each item runs to completion and
  its result or exception is captured. Add an `Outcome` dataclass (exported from `sfvf.context`) with
  `value: Any`, `error: BaseException | None`, and an `ok` property (`error is None`).

### Thread-safe `emit` (required — concurrency introduces concurrent stdout writes)
`ctx.map` runs steps in parallel, so multiple `step` events are emitted from different threads at once.
In `sdk/sfvf/emit.py`, guard the write+flush in `emit()` with a module-level `threading.Lock`, so a
concurrent burst of events yields whole, non-interleaved JSON lines (the supervisor reads stdout
line-by-line; a torn line would corrupt `events.jsonl`). `log`/`stage`/`heartbeat` go through `emit`,
so they are covered.

### Not in scope (deferred)
Cancellation between item completions (§4.7 "Cancellation is honoured between item completions") ties
to the stop-sentinel mechanism and is deferred to a later increment. Do not implement it here.

## Scope — files you may change
- `sdk/sfvf/context.py` (`ctx.map` + `Outcome`)
- `sdk/sfvf/emit.py` (thread-safe lock around the write)

## Do NOT touch
- `tests/**` (make the reviewer test pass), `sdk/sfvf/cache.py`, `sdk/sfvf/runner.py`, `app/`, the
  frontend, `.github/`, `docs/`, `handoff/`. No dependencies. Do not weaken any test or CI.

## Acceptance
- `tests/sdk/test_map.py` passes; all existing tests still pass. Full six-command gate green.
- `sdk/` is mypy-strict — annotate fully (typing of the `inputs`/`fn`/`label` callables and `Outcome`).

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
Add ctx.map to run many steps of one family in parallel with results in input order, and make emit thread-safe so concurrent step events cannot tear a line.
```
(Cursor appends its `Co-authored-by` trailer automatically.)

## Report back
Print the files changed, the commit hash, and the final pytest count.
