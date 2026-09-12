# TASK E-4a — run files listing endpoint (records/replay Artifacts panel)

## Goal (one sentence)
Add a `GET /api/workflows/{workflow_id}/runs/{run_id}/files` endpoint that lists a run's serveable
files (run-relative path + size), so the records/replay view can enumerate a run's artifacts.

## Why
The records/replay run-detail view (the approved mockup's `#p-video`, its Artifacts panel) needs to
enumerate a run's files — `final.mp4`, `artifacts/script.md`, `artifacts/voice.wav`,
`artifacts/composition.html`, `artifacts/captions.srt`. The run detail already returns
`video_records` (with `self_review`, cost, status) and events give the steps; the only missing piece
is a file *listing* — the existing endpoint only *serves* one file by path
(`GET .../files/{path:path}`). This adds the sibling listing route.

## Frozen contract (already committed — do NOT edit)
`tests/api/test_run_files_listing.py`. It requires:
- `GET /api/workflows/{workflow_id}/runs/{run_id}/files` → 200 with
  `{"files": [{"path": <run-relative posix string>, "size": <int bytes>}, ...]}`.
- Paths are run-relative, posix (`/`), never absolute.
- `context.json` is NEVER listed (any depth) — it holds injected secrets and the serving endpoint
  already blocks it.
- Files under an internal dot-directory (`.steps`, `.library-overlay`, any path component starting
  with `.`) are skipped — run state, not artifacts.
- An empty/only-internal run returns `{"files": []}`.
- Unknown run (no `request.json`? — no: the listing keys on the run *dir*; match the serving
  endpoint's guards) → 404; unsafe `run_id` (`is_safe_path_segment` false) → 404; unknown workflow
  → 404. Mirror `get_run_file`'s guard order exactly.

## What to implement (`app/api/runs.py` only)
- Add Pydantic response models near the others, e.g. `RunFileOut(path: str, size: int)` and
  `RunFilesOut(files: list[RunFileOut])`.
- Add `@router.get("/workflows/{workflow_id}/runs/{run_id}/files", response_model=RunFilesOut)` —
  place it BEFORE the existing `.../files/{path:path}` route is fine (FastAPI matches the exact
  `/files` path distinctly from `/files/{path}`; verify no shadowing).
  - Guard exactly like `get_run_file`: `_require_workflow(request, workflow_id)`;
    `if not is_safe_path_segment(run_id): 404`; resolve `run_dir = _runs_dir(request)/workflow_id/
    run_id`; `if not run_dir.is_dir(): 404`.
  - Walk `run_dir` recursively for regular files. For each, compute the run-relative posix path
    (`p.relative_to(run_dir).as_posix()`). SKIP a file if its name is `context.json` OR any path
    component starts with `.` (internal dot-dir). Emit `{"path", "size": p.stat().st_size}`.
  - Sort the result by `path` for a deterministic response.
  - Confinement: only files genuinely under `run_dir` (a `rglob`/`os.walk` of `run_dir` stays inside
    by construction; do not follow symlinks out — use `Path.rglob` which does not resolve symlinks
    into the walk, and skip any entry whose resolved path escapes `run_dir`).

## Constraints / do-nots
- Do NOT change the existing `get_run_file` serving endpoint, the detail/list/events endpoints, or
  `app/core/records.py`. Do NOT edit any test.
- No new dependencies. Keep `ruff`, `ruff format`, and `mypy --strict` clean; match the file's style.

## Scope
- `app/api/runs.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_run_files_listing.py tests/api/test_run_files.py tests/api/test_runs.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
