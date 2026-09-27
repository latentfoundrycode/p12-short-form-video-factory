# TASK F2a-browsability — keep archived workflows' runs browsable (R-011)

RED-first: `tests/api/test_workflow_cards.py::test_archived_workflow_runs_stay_browsable` is RED.
Do NOT edit tests.

## The requirement
An archived workflow (run output under `runs_dir/<id>/` but no folder under `workflows/`) is NOT in
the registry snapshot. Today `app/api/runs.py::_require_workflow` (~line 379) returns 404 when
`_holder(request).get(workflow_id)` is None, so archived videos can't be browsed. R-011 says they
must stay browsable.

## Fix (app/api/runs.py)
- Add a helper (e.g. `_require_workflow_readable(request, workflow_id)`) used by the READ/LIST
  routes — list runs, get run, run files, run events, pending gates — that accepts the id when it is
  EITHER in the registry (`_holder(request).get(id)` not None) OR exists as a subdir of the runs dir
  (`(_runs_dir(request) / id)` is a directory containing at least one run with `request.json`; guard
  the id with `app.paths.is_safe_path_segment`).
- Keep the existing registry-only `_require_workflow` for the MUTATION/launch routes
  (launch/start, stop, delete, clear-failed, submit-quality, submit-gate) — archived workflows have
  no code to run, so those correctly stay 404.
- Use `_runs_dir(request)` (the app/api/runs.py accessor that returns `app.state.runs_dir`).

## Done when
- `./.venv/Scripts/python.exe -m pytest tests/api tests/core -q` — the only failures are the 2
  pre-existing httpx `..`-path cases (test_delete_run_rejects_unsafe_run_id, test_unknown_workflow_is_404).
- `ruff check .`, `ruff format --check .`, `mypy` clean. No test files edited.
- End with an `Assumed, not verified` list (or `none`).
