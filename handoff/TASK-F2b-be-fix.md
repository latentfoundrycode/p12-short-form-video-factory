# TASK F2b-be-fix — last_run: reject bool events + never 500 the list

Review B blockers. RED-first: tests/api/test_workflow_cards.py::test_last_run_ignores_bool_stage_and_progress
and ::test_undecodable_events_file_does_not_500_the_list are RED. Do NOT edit tests.

## 1. Reject bool in stage/progress parsing (app/core/estimate.py)
`_parse_stage_event` / `_parse_progress_event` accept `index`/`total`/`done` via `isinstance(value, int)`,
which is True for `True`/`False`. A `{"index": true}` event is coerced to 1 and overwrites the real
stage. Fix: reject bool before accepting an int — `if isinstance(value, bool) or not isinstance(value, int): skip`
for every numeric field. A malformed (incl. bool) stage/progress event is SKIPPED (the last good one is kept).

## 2. Never let a bad events.jsonl 500 the list (app/core/estimate.py)
`read_events` reads the file as UTF-8, so invalid bytes raise `UnicodeDecodeError` (a `ValueError`),
and the events loop in `last_run_snapshot` only catches `OSError`, so `GET /api/workflows` 500s for
EVERY card. Fix: broaden the guard around the events read/loop to also catch `ValueError` (which
covers `UnicodeDecodeError`) and return the run's status with `stage=None, progress=None` — never
raise. (The status still comes from request.json.)

## Done when
- ./.venv/Scripts/python.exe -m pytest tests/api/test_workflow_cards.py tests/api/test_workflows.py -q passes.
- Full tests/api + tests/core: only the 2 pre-existing httpx `..`-path failures (test_supervisor
  silence-timer tests may flake under CPU load — unrelated, ignore).
- ruff check ., ruff format --check ., mypy clean. No test files edited.
- End with an `Assumed, not verified` list (or `none`).
