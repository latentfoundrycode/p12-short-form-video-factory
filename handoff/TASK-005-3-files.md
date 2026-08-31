# TASK-005-3 — Serve run files with HTTP range requests

## One-line task and why
Serve files under a run folder (the finished video, artifacts, gate images) over HTTP with
**range-request support**, path-confined to that run. Range support is mandatory so a browser can
seek within a video (Architecture §1.3: "Without it, video plays from the start but cannot be
seeked"); the same route later backs gate-artifact review (§3.5/§6). Third and final backend
increment of Task 5; the frontend is 005-4.

## Verified fact you can rely on (do not re-implement range logic)
The installed **Starlette 1.6.0 `FileResponse` handles HTTP Range natively** — I confirmed
empirically: a plain GET returns 200 with `Accept-Ranges: bytes`; a `Range: bytes=10-19` request
returns **206** with a correct `Content-Range: bytes 10-19/<size>` and the correct slice; an
unsatisfiable range returns **416**. So the endpoint just needs to resolve a confined path and
return `FileResponse(path)` — do NOT hand-roll range parsing, 206, or Content-Range.

## Context you need (read before coding)
- `app/api/runs.py` — the run router (built in 005-1/005-2). Add the new endpoint HERE, same style
  (`_require_workflow`, `_runs_dir(request)`, `is_safe_path_segment`).
- `app/api/workflows.py` — the existing `workflow_thumbnail` endpoint is your model for confined
  `FileResponse` serving: it uses `safe_join(...)`, checks `path.is_file()`, and returns
  `FileResponse(path, media_type=...)`. Mirror it. Serve **inline** (do not pass a `filename=`
  argument — that would force a download and break inline video playback).
- `app/paths.py` — `safe_join(folder, relative) -> Path | None` (rejects absolute paths, drive
  anchors, and any `..` segment) and `is_safe_path_segment`.

## Endpoint
`GET /api/workflows/{workflow_id}/runs/{run_id}/files/{path:path}`
- `{path:path}` is a catch-all capturing the sub-path within the run folder (e.g. `01/final.mp4`,
  `01/artifacts/script.md`, `shared/artifacts/...`).
- Validate `workflow_id` and `run_id` with `is_safe_path_segment`; 404 if unsafe or the run dir
  (`<runs_dir>/<workflow_id>/<run_id>`) does not exist.
- Confine the sub-path: `target = safe_join(run_dir, path)`; if `safe_join` returns `None` → 404.
  **Then, defense in depth**, resolve and verify containment: `resolved = target.resolve()` and
  require `resolved.is_relative_to(run_dir.resolve())`; otherwise 404. (Guards against symlink or
  edge escapes that a pure string check misses.)
- If `resolved` is not an existing file → 404.
- Return `FileResponse(resolved)` (it auto-detects media type from the extension; you may pass an
  explicit `media_type` via `mimetypes.guess_type` mirroring the thumbnail endpoint, defaulting to
  `application/octet-stream`). Do not set an attachment disposition.

Do not leak absolute paths in any error body (raise bare `HTTPException(status_code=404)` as the
existing endpoints do).

## TDD-first — write failing tests before implementing
Add tests (extend `tests/api/test_runs.py` or a new `tests/api/test_run_files.py`; reuse the
existing fixtures/helpers — `_client`, `_install_stub`, the autouse supervisor-state cleaner).
You can write files directly into a run folder under the injected `runs_dir` rather than launching
a real run. Cover at least:
- **full GET** of a known file → 200, body equals the bytes, `Accept-Ranges: bytes` present.
- **range GET** (`Range: bytes=a-b`) → **206**, `Content-Range: bytes a-b/<size>`, body equals the
  requested slice.
- **nested path** (e.g. `01/artifacts/script.md`) served correctly.
- **traversal blocked**: a path containing `..` (e.g. `../../etc/hosts` or `01/../../secret`) → 404,
  and nothing outside the run dir is served.
- **missing file** under an existing run → 404; **unknown run** → 404; **unsafe run_id** → 404.

Confirm the tests fail first (no endpoint), then implement until green.

## Scope — files you may change
- `app/api/runs.py` (add the endpoint)
- `tests/api/test_runs.py` and/or `tests/api/test_run_files.py`

## Do NOT touch
- `app/core/*`, `app/registry/*`, `app/paths.py`, `app/main.py`, the SDK (`sdk/`), the frontend
  (`frontend/`), or anything under `docs/` or `handoff/`.
- Do NOT add dependencies. Do NOT hand-roll range/Content-Range handling (FileResponse does it).
- Do NOT add auth, directory listing, upload, or write endpoints — read-only single-file serving
  only.

## Gate — run all six before committing (worktree root, PowerShell)
```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```
All clean. Report the final pytest count (142 + your new tests).

## Commit message (house style — imperative subject stating change and rationale)
```
Serve run files with range support so the browser can seek within a video and review gate artifacts, confined to the run folder.
```
(Cursor appends its `Co-authored-by` trailer automatically.)

## Report back
Print the files changed, the commit hash, and the final pytest count.
