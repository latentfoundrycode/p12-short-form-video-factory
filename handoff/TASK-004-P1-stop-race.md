# TASK-004-P1 — Close the stop/register race in the supervisor

## One-line task and why
Fix a race in `app/core/supervisor.py` where a subprocess launched in the window between
the stop pre-check and its registration escapes `stop()` entirely — so a hard stop is
reported accepted but never terminates the process, hanging the run. This defends the
`stop()` contract in Architecture §3.4 ("A second stop terminates the whole process tree
immediately") and §5.3 (the supervisor "handles ... cancellation").

## Background — the exact defect
In `_run_one_video` the worker checks `state.stop_requested` under the lock
(around supervisor.py:593-601), then does I/O (context write, records) and only calls
`state.register_proc(...)` later (around supervisor.py:631). `_run_prepare` has the same
shape: it launches the prep proc and calls `register_proc("prep", ...)` at
supervisor.py:504 after the process already exists.

`stop()` (supervisor.py:325-339) calls `state.request_stop(mode)`, which under the lock
sets `stop_requested = True` and returns a **snapshot** of `self.procs`. Any process
registered *after* that snapshot is never signalled or killed. Reproduced live: a hard
stop issued in this window left a `stubborn` subprocess running and the run hung ~8s until
the stub exited on its own.

## Required behaviour (state precisely; do not "improve away")
1. A subprocess that is registered while `stop_requested` is already `True` must have the
   **pending stop action applied to it immediately**, with the same semantics `stop()`
   uses per process:
   - `graceful`: `touch` the `STOP_SENTINEL` file in that process's folder, then send the
     soft signal (`_send_soft_signal`).
   - `hard`: `kill_tree(proc)`.
   This must hold for **both** video subprocesses (`_run_one_video`) and the prepare
   subprocess (`_run_prepare`).
2. The fix must be correct in **both** orderings, because `register_proc` and
   `request_stop` both take `state.lock` and therefore serialize:
   - stop-first: `register_proc` observes `stop_requested` and the caller applies the stop;
   - register-first: `request_stop`'s snapshot already includes the proc and `stop()`
     applies the stop.
   Applying the action in both orderings is safe: `touch` + `_send_soft_signal` +
   `kill_tree` are all idempotent / no-ops on an already-exited process. **Do not** add
   bookkeeping to make the action happen "exactly once" — double application is harmless
   and simpler; keep it simple.
3. Do not change the existing lock discipline: `register_proc` must not perform a
   blocking `kill_tree`/signal **while holding `state.lock`** (that would stall every
   `append_event`). Read the pending mode under the lock, return it, and let the caller
   act **after** releasing the lock. Mirror how `request_stop` already returns a snapshot
   for the caller to act on outside the lock.

## Suggested shape (reuse over rebuild — follow existing idioms in this file)
- Factor the per-process stop action `stop()` already performs (the body of its
  `for _key, proc, folder in snapshot:` loop) into a small module-level helper, e.g.
  `_apply_stop(mode, proc, folder)`, and call it from both `stop()` and the new
  post-register check so there is exactly one definition of "how to stop one process."
- Change `_RunState.register_proc` to return the pending stop mode under the lock:
  `return self.stop_mode if self.stop_requested else None` (type `StopMode | None`).
- In `_run_one_video` and `_run_prepare`, after `register_proc(...)`, if it returned a
  mode, call `_apply_stop(mode, proc, folder)`.
- Keep everything else — the aggregate-status logic, the silence watchdog, the
  prepare-once flow — untouched.

## TDD-first — write the failing regression test before the fix
Add a test to `tests/core/test_supervisor.py` that forces the losing interleaving and
proves the process is now terminated. Use the existing `popen`-injection seam (see
`test_prepare_feeds_shared_into_video_context`, which wraps `subprocess.Popen` and reads
`request.json`). Concretely:

- A `popen` wrapper that, for the video subprocess (`cwd.name == "01"`), reads the
  `run_id` from `<run_dir>/request.json` and calls `stop(run_id, mode="hard")` **before**
  creating and returning the real `subprocess.Popen`. This guarantees the stop snapshot
  runs before `register_proc`.
- Drive the `stubborn` stub (it ignores signals and sleeps 8s, so only an explicit
  `kill_tree` ends it) via the existing `_run_in_thread` / `_join_run` helpers with a
  timeout of ~5s. Before the fix, the run hangs 8s and `_join_run`'s
  `assert not thread.is_alive()` fails; after the fix, the process is killed and the run
  returns promptly.
- Assert the request and video both end `status == "stopped"`.

Confirm the test **fails on the unmodified code first**, then implement the fix and
confirm it passes. Keep it in the same style as the neighbouring stop tests.

## Scope — files you may change
- `app/core/supervisor.py` (the fix)
- `tests/core/test_supervisor.py` (the regression test)

## Do NOT touch
- Any other file. In particular: do not change the event protocol, `to_event`,
  `app/core/proc.py`, `app/core/records.py`, the records models, the context contract, or
  anything under `docs/` or `handoff/`.
- Do not add dependencies.
- Do not alter unrelated behaviour of `stop()`, the silence watchdog, or aggregate status.

## Gate — run all six before committing (from the worktree root, PowerShell)
```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```
Expected: all clean; pytest count is 127 (the existing 126 plus your new regression test).

## Commit message (house style — imperative subject stating change and rationale)
```
Apply a pending stop to a subprocess registered mid-launch so a hard stop cannot miss it and hang the run.
```
(Cursor appends its `Co-authored-by` trailer automatically.)

## Report back
Print the list of files you changed, the commit hash, and the final pytest count.
