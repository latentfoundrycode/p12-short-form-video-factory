# TASK-005-1 — Run API: launch, stop, read

## One-line task and why
Expose the already-built supervisor over HTTP so the frontend can start a generation
request, stop it, and read its records. This is the first increment of Stage 2 · Task 5
(Architecture §5.3 supervisor, §6 frontend routes, §4 stored data). SSE live streaming
(005-2) and file serving (005-3) come next and are OUT of scope here.

## Context you need (read these before coding)
- `app/core/supervisor.py` — `run_request(workflow_dir, *, params, video_count, concurrency,
  runs_dir=None, ensure_env=..., popen=..., silence_limit_default=...) -> EnvBlocked | RunBusy
  | RequestRecord`. It is **blocking**: it runs the whole request (prepare + all videos) before
  returning. It also exposes `stop(run_id, *, mode) -> StopAccepted | NotRunning` and the
  dataclasses `RunBusy`, `StopAccepted`, `NotRunning`, and `EnvBlocked` (from `app.core.env`).
- `app/core/records.py` — `read_request(run_dir) -> RequestRecord`, `read_video(video_dir) ->
  VideoRecord`, and the `RequestRecord`/`VideoRecord` pydantic models. Use these; do not re-parse
  JSON by hand.
- `app/api/workflows.py` — the existing router style (APIRouter(prefix="/api"), pydantic
  response models, `RegistryHolder` in `request.app.state.registry`, `_holder(request)`,
  `is_safe_path_segment`/`safe_join` from `app.paths`). **Mirror these idioms.**
- `app/main.py` — `create_app(...)` wires routers and mounts the SPA. You will include a new
  router here.
- `app/paths.py` — `RUNS_DIR`, `WORKFLOWS_DIR`, `is_safe_path_segment`, `safe_join`.
- Stub workflows live in `tests/stubs/` (e.g. `succeeds`, `cooperates`, `fails`). Existing
  supervisor tests in `tests/core/test_supervisor.py` show how to drive runs with an injected
  `ensure_env` returning `EnvReady(python=Path(sys.executable))`.

## The design problem to solve: async launch that still returns the run id
`POST /runs` must not block for the whole run. But `run_request` allocates the run id
*inside itself* (after the busy-check and env-ensure) and only returns it when the run finishes.
Required behaviour:

1. The endpoint launches `run_request` on a background **daemon thread** (a small run-manager;
   see below) and returns as soon as **admission** resolves — i.e. as soon as the run id is
   known, or the run is refused. It must NOT wait for prepare/videos to finish.
2. To learn the run id at admission time, add a single optional hook to `run_request`:
   `on_started: Callable[[str], None] | None = None`, called **exactly once with the run id
   immediately after the run id is allocated** (right after `allocate_run(...)` succeeds, inside
   `run_request`). Default `None` → existing behaviour and all existing tests unchanged. This is
   the ONLY change to `supervisor.py` and it must be minimal (one parameter + one call).
3. The run-manager launches the thread with an `on_started` that records the run id and signals a
   `threading.Event`; the endpoint waits on that event OR on the thread finishing early (which
   happens when `run_request` returns `RunBusy` or `EnvBlocked` before allocating). Resolve:
   - run id signalled → **202** `{"run_id": "..."}`.
   - thread returned `RunBusy` → **409** (workflow already has an active run).
   - thread returned `EnvBlocked` → **422** `{"reason": "..."}`.
   Note: admission includes env-ensure, so the response waits through env setup. For an existing
   venv this is fast; a first-time venv build makes it slow. That is acceptable for this
   increment (tests inject a ready env). Record it as a known limitation in a code comment; do
   not try to make env setup async here.

## Endpoints (all under the existing `/api` prefix; new router in `app/api/runs.py`)
Resolve the workflow from the registry holder (`request.app.state.registry`). Validate
`workflow_id` and `run_id` with `is_safe_path_segment`; 404 on anything unsafe or unknown.
Use `RUNS_DIR` for the runs root, but allow it to be overridden for tests (see Testability).

1. `POST /api/workflows/{workflow_id}/runs`
   - Body (pydantic): `{ "params": dict, "video_count": int >= 1, "concurrency": int >= 1 }`.
   - 404 if the workflow id is unknown to the registry; 422 if the workflow is present but
     invalid (has an error-severity problem) — do not launch an invalid workflow.
   - Launches the run (per the design above). Responses: 202 `{run_id}`, 409 busy, 422 env-blocked.
2. `POST /api/workflows/{workflow_id}/runs/{run_id}/stop`
   - Body: `{ "mode": "graceful" | "hard" }`.
   - Calls `stop(run_id, mode=...)`. `StopAccepted` → 200 `{"run_id","mode"}`; `NotRunning` →
     404. (A finished or unknown run is `NotRunning`.)
3. `GET /api/workflows/{workflow_id}/runs`
   - Lists runs for that workflow by reading `runs/<workflow_id>/*/request.json` via
     `read_request`. Return a list of summaries (run_id, status, started_utc, ended_utc, and the
     per-video statuses), **newest first** by run id. Missing runs dir → empty list.
4. `GET /api/workflows/{workflow_id}/runs/{run_id}`
   - Returns the full `request.json` plus each present `video.json` (read with `read_video`;
     a video folder without `video.json` yet is simply omitted or shown as its request-level
     status). 404 if the run dir / request.json does not exist.

Define explicit pydantic response models (mirror `WorkflowOut` style). Do not leak absolute
filesystem paths in any response.

## The run-manager
Put it in `app/api/runs.py` (or `app/core/run_manager.py` if that reads cleaner — your call, but
keep it out of `supervisor.py`). It owns launching `run_request` on a daemon thread and the
admission handshake. It must not add authoritative in-memory state beyond what is needed to hand
back the run id; run status is always read from the record files (durable-state-first, §5.3/§15).
Injecting `runs_dir`, `ensure_env`, and `popen` through to `run_request` must be possible so tests
can drive it without real venvs.

## Testability (so the reviewer's tests can drive it)
- `create_app(...)` (in `app/main.py`) must let a test point the runs API at a temp runs dir and
  supply a test `ensure_env`/`popen`. Add optional parameters to `create_app` and/or store an
  injectable config on `app.state` — mirror how `RegistryHolder` is placed on `app.state`. Keep
  production defaults (`RUNS_DIR`, real `subprocess.Popen`, real `ensure_env`) unchanged.
- Use FastAPI's `TestClient` in tests.

## TDD-first — write failing tests before the implementation
Add `tests/api/test_runs.py`. Cover at least:
- **launch + read:** start the `succeeds` stub (video_count=1) → poll `GET …/{run_id}` until the
  request status is terminal → assert `complete` and the video record present. (Because launch is
  async, poll with a bounded deadline; mirror the `_wait_*` helpers in `test_supervisor.py`.)
- **list:** after a run, `GET …/runs` returns it, newest-first.
- **stop:** start `cooperates` (video_count=1), wait for its first event/run dir, `POST …/stop`
  `{mode:"graceful"}` → 200; the run ends `stopped`.
- **busy:** while one run is active, a second `POST …/runs` for the same workflow → 409. (Use an
  `ensure_env` that blocks until released, as `test_single_active_guard_refuses_second_run` does.)
- **env-blocked:** an `ensure_env` returning `EnvBlocked(...)` → 422 with the reason, and no run
  folder created.
- **unknown/invalid workflow:** unknown id → 404.
- Also add one test to `tests/core/test_supervisor.py` asserting `on_started` fires exactly once
  with the allocated run id on a normal run, and is not called on `RunBusy`/`EnvBlocked`.

Confirm the new tests fail first (endpoints/param not present), then implement until green.

## Scope — files you may change
- `app/api/runs.py` (new), and `app/core/run_manager.py` (new, only if you choose that split)
- `app/main.py` (wire the new router; add optional injection params to `create_app`)
- `app/core/supervisor.py` (ONLY the `on_started` hook: one optional param + one call)
- `tests/api/test_runs.py` (new), `tests/core/test_supervisor.py` (one added test)

## Do NOT touch
- `app/core/records.py`, `app/core/proc.py`, `app/core/events.py`, `app/registry/*`, the SDK
  (`sdk/`), the frontend (`frontend/`), or anything under `docs/` or `handoff/`.
- Do NOT add SSE, an events stream endpoint, or file/range serving — those are later increments.
- Do NOT add dependencies. Do NOT change existing supervisor behaviour beyond the `on_started`
  hook. Do NOT introduce authoritative in-memory run state (read status from record files).

## Gate — run all six before committing (worktree root, PowerShell)
```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```
All must be clean. Report the final pytest count (it will be 127 + your new tests).

## Commit message (house style — imperative subject stating change and rationale)
```
Serve start/stop/read of a generation request over HTTP so the frontend can drive the supervisor without blocking on the run.
```
(Cursor appends its `Co-authored-by` trailer automatically.)

## Report back
Print the list of files changed, the commit hash, and the final pytest count.
