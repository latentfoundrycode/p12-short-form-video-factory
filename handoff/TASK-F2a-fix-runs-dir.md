# TASK F2a-fix — remove the runs_dir test-coupling heuristic

app/api/workflows.py added `resolve_runs_dir_for_request`, which, when `runs_dir` is the default
RUNS_DIR and `workflows_dir` is non-default, returns `workflows_dir.parent / "runs"`. That is a
test-isolation hack living in production code (it infers the runs root from the workflows folder).
The tests now pass an explicit `runs_dir`, so the heuristic is no longer needed.

Fix (app/api/workflows.py):
- Delete `resolve_runs_dir_for_request`.
- Make `_runs_dir(request)` simply return the configured runs dir from app state, mirroring
  app/api/runs.py `_runs_dir`:
  `return cast(Path, request.app.state.runs_dir)` (keep the RUNS_DIR fallback only if state is unset,
  matching the existing accessor pattern).
- Remove now-unused imports (WORKFLOWS_DIR if nothing else uses it).

Do NOT edit any test file. When done run:
`./.venv/Scripts/python.exe -m pytest tests/api tests/core -q` (only the 2 pre-existing httpx `..`-path
failures may remain), and `-m ruff check .`, `-m ruff format --check .`, `-m mypy` clean.
End with an `Assumed, not verified` list (or `none`).
