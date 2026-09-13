# TASK fix — stop the composition-check / render node launch opening console windows (Windows)

## Goal (one sentence)
Spawn `node` from `sfvf.media.graphics._run` with `CREATE_NO_WINDOW` on Windows so `node` and the
`chrome-headless-shell` / FFmpeg processes it launches never open a console window (they were piling
up dozens of orphaned console tabs during test runs).

## Background (verified)
`sdk/sfvf/media/graphics.py::_run` is the single point that spawns `node` (used by BOTH the
composition `check()` and `render`). Its `subprocess.Popen(...)` passes no `creationflags`, so on
Windows the child `node` — and the `chrome-headless-shell` / FFmpeg it spawns — inherit/open a
console window. `dom_check.mjs` already closes the browser + server in a `finally`, so teardown is
not the issue; the missing piece is console suppression at the OS-process level. `import sys` and
`import subprocess` are already present in the file.

## Frozen contract (already committed — do NOT edit)
`tests/sdk/test_graphics_no_console_window.py`: spies on `subprocess.Popen` and asserts `_run` passes
`creationflags == (subprocess.CREATE_NO_WINDOW on win32 else 0)`.

## What to implement — `sdk/sfvf/media/graphics.py` ONLY

1. Add a module-level constant near the other module constants (after the imports), with a short
   comment:
   ```python
   # Windows: keep node — and the chrome-headless-shell / FFmpeg it spawns — from opening a console
   # window. CREATE_NO_WINDOW exists only on Windows; 0 is a no-op elsewhere.
   _NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
   ```
   (mypy narrows `sys.platform == "win32"`, so the win32-only attribute is only referenced on
   Windows — this type-checks on Linux CI. If mypy on Linux still objects, use
   `_NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)` instead.)

2. In `_run`, add `creationflags=_NO_WINDOW` to the existing `subprocess.Popen(...)` call (the one
   with `stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, ...`). Add ONLY that keyword;
   change nothing else in `_run` or the file.

## Constraints / do-nots
- Touch ONLY `sdk/sfvf/media/graphics.py` (implementation) and `docs/HARDENING.md` (the supervisor
  appends an advisory note — see Scope). Do NOT edit any test, `dom_check.mjs`, or any other file.
- Do NOT change behaviour other than console suppression. No new dependency.
- Keep `ruff check`, `ruff format --check`, and `mypy --strict` (`mypy sdk app`) clean; wrap ≤100 cols.

## Scope
- `sdk/sfvf/media/graphics.py`
- `docs/HARDENING.md`

(The builder produces only the `graphics.py` change; `docs/HARDENING.md` is a supervisor-appended
advisory note — H40 — the same way H32–H39 landed through their PRs, not part of the code change.)

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/sdk/test_graphics_no_console_window.py -q` → passes.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
