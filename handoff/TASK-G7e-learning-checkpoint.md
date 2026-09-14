# TASK G-7e — "since the last learning run" checkpoint (§5.11)

## Goal (one sentence)
Persist a per-workflow last-learned marker on accept, gather/count only the labels from Generation
Requests that started after it, and surface the real `last_learned` in `GET /api/learning`.

## Governing spec (verbatim — Architecture §5.11)
> gather every `video.json` containing quality answers **since the last learning run**, load that
> workflow's criteria files together with its current rules and skills, and run the SkillOpt-derived
> optimiser to propose bounded edits.

The marker is the natural "run" anchor: a Generation Request counts as new when its `started_utc` is
after the marker. (Known, accepted limitation: a quality answer added to an OLDER request after a
learning run is not re-counted — precise per-answer timing would need a quality timestamp; out of
scope.) The marker must live OUTSIDE the workflow tree — learning may only write `rules/`, `skills/`,
`archive/` inside a workflow.

## Frozen contract (already committed — do NOT edit)
`tests/api/test_learning_checkpoint.py`.

## What to implement (FOUR files)

### 1) `app/learning/state.py` (new) — the marker store
```python
from __future__ import annotations
import json
from pathlib import Path
from app.paths import is_safe_path_segment
```
- `read_last_learned(state_dir: Path, workflow_id: str) -> str | None` — return the stored ISO
  timestamp for the workflow, or `None` when there is no marker (missing dir/file, unsafe id, or
  unreadable/%malformed JSON → treat as no marker; never raise). Read
  `state_dir / f"{workflow_id}.json"`, a JSON object `{"last_learned": "<iso>"}`; return the string
  value (or None if absent/non-string). Guard `is_safe_path_segment(workflow_id)` → None if unsafe.
- `write_last_learned(state_dir: Path, workflow_id: str, iso: str) -> None` — create `state_dir` if
  needed and write `{"last_learned": iso}` to `state_dir / f"{workflow_id}.json"` (UTF-8). Guard the
  id with `is_safe_path_segment`; do nothing if unsafe.

### 2) `app/learning/engine.py` — filter gather by the marker
- Add a keyword param `since: str | None = None` to `_gather_labels(runs_dir, workflow_id, *, since=None)`
  and to `run_learning(..., since: str | None = None)` (keyword-only, defaulted — the G-5 contract
  callers pass neither, so this stays backward-compatible).
- In `_gather_labels`, after `read_request(run_dir)` yields the request record, when `since is not
  None` SKIP the run unless `request.started_utc > since` (plain string comparison of ISO-8601 UTC
  timestamps; both are the `format_utc_z` shape). `run_learning` threads `since` into `_gather_labels`.

### 3) `app/api/learning.py` — wire the marker in + surface it
- Import `read_last_learned, write_last_learned` from `app.learning.state`, and a state-dir accessor
  `_learning_state_dir(request) -> Path` = `request.app.state.learning_state_dir`.
- `run` endpoint: `since = read_last_learned(_learning_state_dir(request), workflow_id)`; pass it as
  `run_learning(..., since=since)`.
- `accept` endpoint: after `accept_learning(...)` succeeds, `write_last_learned(
  _learning_state_dir(request), workflow_id, ids.format_utc_z(ids.utc_now()))` (import
  `from app.core import ids`). (`reject` does NOT write a marker.)
- `list_learning` (`GET /learning`): for each workflow, `marker = read_last_learned(state_dir,
  entry.folder_name)`; set `last_learned=marker` (instead of the current hard-coded `None`); pass
  `marker` into the label count.
- `_label_count(runs_dir, workflow_id, since=None)`: add the same `since` filter as the engine —
  read each run's request, skip unless `started_utc > since`.

### 4) `app/main.py` — the new create_app kwarg
- Add `learning_state_dir: Path | None = None` to `create_app`; set
  `application.state.learning_state_dir = learning_state_dir or (APP_ROOT / "state" / "learning-state")`
  (`APP_ROOT` is already imported for `learning_staging_dir`). Disjoint from `WORKFLOWS_DIR`.

## Constraints / do-nots
- Touch ONLY: `app/learning/state.py` (new), `app/learning/engine.py`, `app/api/learning.py`,
  `app/main.py`. Do NOT edit the test, the SDK, `accept.py`, `optimizer.py`, `completion.py`, or the
  frontend. Reuse existing helpers; do not reimplement them.
- The marker file must never be written inside a workflow directory.
- Keep `ruff check .`, `ruff format --check .`, and `mypy sdk app` clean; ≤100 cols.

## Scope
- `app/learning/state.py`
- `app/learning/engine.py`
- `app/api/learning.py`
- `app/main.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_learning_checkpoint.py -q` → all pass.
- `-m pytest -q` (full) → green (the G-5 engine tests must still pass — `since` defaults to None).
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
