# TASK F2b-backend — last_run card state on WorkflowOut

Backend for R-006 (running + stage) and R-007 (outline colours), PRD §8.1. RED-first: the frozen
tests in tests/api/test_workflow_cards.py (test_no_runs_has_null_last_run, test_last_run_*,
test_archived_card_carries_last_run) and the updated WORKFLOW_FIELDS in tests/api/test_workflows.py
are RED. Do NOT edit tests.

## Add to WorkflowOut (app/api/workflows.py)
`last_run: LastRunOut | None = None` where:
- `LastRunOut{ run_id: str, status: str, stage: StageOut | None, progress: ProgressOut | None }`
- `StageOut{ index: int, total: int, label: str }`
- `ProgressOut{ done: int, total: int }`

## Compute it (in _serialize and _serialize_archived, from runs_dir/<id>)
- Find the NEWEST run dir (reuse the newest-first ordering already used — sort run-id dir names
  reverse=True; a run dir is one containing request.json). If none, `last_run = None`.
- status = that run's `RequestRecord.status` (read via app.core.records.read_request).
- stage/progress = read the run's events via app.core.records.read_events (yields (ts, source, event));
  take the LAST event whose `event["t"] == "stage"` -> {index,total,label}, and the LAST whose
  `event["t"] == "progress"` -> {done,total}. Missing -> None. Be tolerant of malformed events
  (skip anything not matching the expected shape; never raise).
- Put a small helper in app/core/estimate.py or a sibling (it already has the newest-run/candidate
  logic); keep the endpoint's disk I/O bounded (read only the newest run's request.json + events.jsonl,
  not every run).

## Notes
- The archived synthetic card must also carry last_run from its orphaned newest run.
- Do not change avg_cost_per_meter/runs_counted/archived behavior.

## Done when
- ./.venv/Scripts/python.exe -m pytest tests/api/test_workflow_cards.py tests/api/test_workflows.py -q passes.
- Full tests/api + tests/core still pass (only the 2 pre-existing httpx `..`-path failures remain).
- ruff check ., ruff format --check ., mypy clean. Frozen tests unmodified.
- End with an `Assumed, not verified` list (or `none`).
