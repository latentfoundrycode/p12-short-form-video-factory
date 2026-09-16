# TASK — suppress Windows console windows on the ordinary-build spawn sites

## Goal (one sentence)
Pass `CREATE_NO_WINDOW` (on Windows) to the subprocess spawns that fire during ordinary
editing/builds — the two Cursor afterFileEdit hooks, `kill_tree`'s `taskkill`, and `env.py`'s python
probe + venv setup — so they run silently instead of popping console windows on the user's desktop.

## Why
On Windows a console child launched from a windowless parent gets its own visible console window
unless created with `CREATE_NO_WINDOW`. The renderer already sets this (`sfvf.media.graphics`), but
these sites never did, so every builder file-edit (which fires `ruff`/`prettier` via the hooks) and
every process teardown / venv setup flashes windows. Use the exact pattern graphics uses:
```python
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
```
and pass `creationflags=_NO_WINDOW` to each `subprocess.run(...)`.

## Frozen contract (already committed — do NOT edit)
`tests/core/test_no_console_window.py` (5 tests). All existing tests must stay green.

## What to change

### 1. `.cursor/hooks/lint_edit.py`
Add `import sys` is already present. Define `_NO_WINDOW = subprocess.CREATE_NO_WINDOW if
sys.platform == "win32" else 0` at module level (after imports) and pass `creationflags=_NO_WINDOW`
to BOTH `subprocess.run(...)` calls (the ruff check --fix and ruff format).

### 2. `.cursor/hooks/format_frontend.py`
`import sys` is already present. Add the same `_NO_WINDOW` module constant and pass
`creationflags=_NO_WINDOW` to the `subprocess.run([node, str(prettier), ...])` call.

### 3. `app/core/proc.py`
Add the `_NO_WINDOW` module constant (uses `sys`, already imported). Pass
`creationflags=_NO_WINDOW` to the `subprocess.run(["taskkill", ...])` call inside `kill_tree`.
(That call is already inside the `if sys.platform == "win32":` branch, so `_NO_WINDOW` will be the
real flag there; keeping the cross-platform constant is fine and matches the graphics pattern.)

### 4. `app/core/env.py`
Add the `_NO_WINDOW` module constant (uses `sys` — add `import sys` if not already imported; check
the file). Pass `creationflags=_NO_WINDOW` to BOTH `subprocess.run(...)` calls: the one in
`default_find_python` (the `py` launcher probe) and the one in `_run_timed` (venv setup).

## Constraints / do-nots
- Touch ONLY `.cursor/hooks/lint_edit.py`, `.cursor/hooks/format_frontend.py`, `app/core/proc.py`,
  `app/core/env.py`. Do NOT edit any test or other file.
- Do NOT change the run-worker spawn in `app/core/supervisor.py` (`_launch_worker` /
  `_process_group_kwargs`) — suppressing its window interacts with the Windows CTRL_BREAK stop signal
  and is handled separately.
- Keep every other kwarg on each call unchanged (`capture_output`, `text`, `timeout`, `check`, `env`).
- Keep `ruff check .`, `ruff format --check .`, `mypy sdk app` clean; ≤100 cols. The hooks live under
  `.cursor/` (outside `sdk`/`app`) — still keep them ruff-clean.

## Scope
- `.cursor/hooks/lint_edit.py`
- `.cursor/hooks/format_frontend.py`
- `app/core/proc.py`
- `app/core/env.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_no_console_window.py -q` → all 5 pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
