# TASK S2b — stop exposing injected secrets (block context.json download + scrub post-run)

**Builder:** Cursor. **Product code only.** Touch `app/api/runs.py` and `app/core/supervisor.py`. Do NOT touch
`tests/`, `docs/`, `handoff/`. The reviewer contract `tests/api/test_secret_exposure.py` is FROZEN.

S2a injects the workflow's allowlisted secrets into each run's `context.json`. This increment closes the two
exposure vectors a decorrelated security review flagged: `context.json` is downloadable via the run-file
endpoint, and it persists the secrets on disk after the run. **No new secret handling — just stop exposing.**

## 1. `app/api/runs.py` — never serve a `context.json`

In `get_run_file`, after the path is resolved and confined (and `resolved.is_file()`), reject any request for a
`context.json`:
```python
if resolved.name == "context.json":
    raise HTTPException(status_code=404)
```
Place it so a `context.json` at any depth (shared/ or a per-video dir) returns 404, while every other run file
still serves normally. (404, not 403 — don't reveal the file exists.)

## 2. `app/core/supervisor.py` — scrub secrets from context.json once the subprocess is done

Add a helper:
```python
def _scrub_context_secrets(context_path: Path) -> None:
    """Blank the `secrets` in an on-disk context.json after its subprocess has consumed it,
    so provider keys don't persist in the run directory. Best-effort; never raises."""
    try:
        if not context_path.is_file():
            return
        data = json.loads(context_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("secrets"):
            data["secrets"] = {}
            write_json_atomic(context_path, data)
    except (OSError, ValueError):
        return
```

Call it once the consuming subprocess has exited (so the workflow still reads its real secrets during the run,
but nothing lingers after):
- in `_run_prepare`, after `proc.wait()` — scrub the shared `context_path` (do it in the `finally`, after
  `state.unregister_proc("prep")`, so it also runs on stop/failure);
- in `_run_one_video`, after that video's `proc.wait()` — scrub that video's `context.json` (likewise in its
  `finally` / after the proc is unregistered).

Timing matters: scrub only AFTER `proc.wait()` returns (the subprocess has finished reading context.json) —
never before, or the workflow would get empty secrets. Use `write_json_atomic` (already imported; it has the
H7 retry). Never log a secret value.

mypy-strict clean. No new dependency. Touch only the two files.

## Acceptance

`tests/api/test_secret_exposure.py` passes (2 tests): a `context.json` under a run dir returns 404 from the
files endpoint while an ordinary file returns 200; after a run that injected an allowlisted secret, every
on-disk `context.json` has `secrets == {}` and the raw value is gone. Existing `tests/api/test_runs.py`,
`test_secret_injection.py`, and the rest of the suite still pass.

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest -q tests/api/test_secret_exposure.py tests/api/test_secret_injection.py tests/api/test_runs.py
```
(The full `pytest` run also shows 3 pre-existing `finalize`/`example_workflow` failures — ONLY the HyperFrames
toolchain missing in this worktree; CI installs it and runs them green. Ignore them.)
