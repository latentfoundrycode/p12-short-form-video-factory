# TASK F-3 — schedules CRUD API (§5.7, `/schedule` page §8.6)

## Goal (one sentence)
Create `app/api/schedules.py` — a REST router over `app/core/schedules.py` that lets the `/schedule`
page list, create, read-one, update, and delete `schedules.json` entries — and wire it into
`app/main.py` with an injectable `schedules_path`.

## Governing spec (verbatim — Architecture §5.7)
> Reads `schedules.json`. When an entry is due it checks two conditions and acts accordingly: if that
> workflow already has an active run, the slot is skipped; if the budget is insufficient, the slot is
> skipped. Otherwise the Generation Request starts with the saved settings.
>
> Missed slots are skipped rather than queued …
>
> Each entry carries the flag determining whether approval gates pause or pass automatically.

The spec is silent on the API shape itself; §5.7 governs the *engine* (F-2, already merged). This
increment is only the management surface the `/schedule` page (v-schedule mockup: a list of entries
+ **Add entry** + **Edit** per row) drives. Owner decision (2026-09-12): `allow_real_spend` is off by
default and `concurrency` defaults 1 — both already enforced by the `ScheduleEntry` model; do not
override them here.

## Frozen contract (already committed — do NOT edit)
`tests/api/test_schedules_api.py`. It pins this exact surface. Read it as the source of truth; the
notes below just explain intent.

Endpoints (all under the existing `/api` prefix):
- `GET  /api/schedules` → `200 {"schedules": [entry, ...]}` (missing file → `{"schedules": []}`).
- `POST /api/schedules` → `201 <entry>` — body is the **writable fields only** (see below); the
  server GENERATES the `id`.
- `GET  /api/schedules/{id}` → `200 <entry>`, or `404` when absent.
- `PUT  /api/schedules/{id}` → `200 <entry>` — body is the writable fields; `id` is taken from the
  path and preserved; `404` when the id is absent.
- `DELETE /api/schedules/{id}` → `204` (empty body), or `404` when absent.

`<entry>` is a JSON object with EXACTLY the nine `ScheduleEntry` fields: `id`, `workflow_id`, `days`,
`time_of_day`, `video_count`, `concurrency`, `params`, `gates_auto`, `allow_real_spend`. Return
`entry.model_dump(mode="json")`.

## What to implement

### 1. `app/api/schedules.py` (new)
Mirror the style of `app/api/statistics.py` and `app/api/runs.py` (both use `APIRouter(prefix="/api")`
and read injected state off `request.app.state`).

- `router = APIRouter(prefix="/api")`.
- A helper `_schedules_path(request) -> Path` returning
  `getattr(request.app.state, "schedules_path", SCHEDULES_PATH)` (import `SCHEDULES_PATH` from
  `app.core.schedules`), cast to `Path`.
- A request-body model `ScheduleWriteIn(BaseModel)` with `model_config = ConfigDict(extra="forbid")`
  carrying only the **writable** fields — i.e. every `ScheduleEntry` field EXCEPT `id`:
  `workflow_id: str`, `days: list[int]`, `time_of_day: str`, `video_count: int = Field(ge=1)`,
  `concurrency: int = Field(default=1, ge=1)`, `params: dict[str, Any] = Field(default_factory=dict)`,
  `gates_auto: bool`, `allow_real_spend: bool = False`. Re-apply the SAME field validators as
  `ScheduleEntry` for `workflow_id` (must be `is_safe_path_segment`), `days` (non-empty, each 0..6),
  and `time_of_day` (24-hour zero-padded `HH:MM`) so a bad body is a `422` (FastAPI turns a body
  `ValidationError` into 422 automatically). Add a one-line comment noting these mirror
  `ScheduleEntry` deliberately. (`id` is not a writable field, so a client-sent `id` is an unknown
  field → 422 under `extra="forbid"` — the contract locks this.)
- `id` generation: `uuid.uuid4().hex` (a safe path segment). Build the stored entry as
  `ScheduleEntry(id=<new_or_path_id>, **body.model_dump())`.
- Persistence uses `read_schedules` / `write_schedules` from `app.core.schedules`. Every mutation is
  READ-MODIFY-WRITE and MUST be serialised under a module-level `threading.Lock()` (F-2 polls the same
  file; two concurrent POSTs must not lose an update). Hold the lock across the read+write of a single
  request; `GET` reads need not take it.
- Handlers:
  - `list_schedules` → `SchedulesOut(schedules=[...])`. Define response models `ScheduleEntryOut`
    mirroring the nine fields, and `SchedulesOut(schedules: list[ScheduleEntryOut])` — OR simply
    return dicts via `model_dump`; either is fine as long as the JSON matches the contract. Preferred:
    typed response models so the OpenAPI stays honest.
  - `create_schedule(body)` → append, write, return `201`. Use
    `from fastapi import status` + a `JSONResponse(status_code=201, content=entry.model_dump(mode="json"))`
    or set `status_code=status.HTTP_201_CREATED` on the route with a return-model.
  - `get_schedule(id)` → find by id or `raise HTTPException(404)`. Guard `id` with
    `is_safe_path_segment` (→ 404 on a bad segment), matching `runs.py`.
  - `update_schedule(id, body)` → under the lock: load, find index by id (404 if absent), replace with
    `ScheduleEntry(id=id, **body.model_dump())`, write, return the updated entry.
  - `delete_schedule(id)` → under the lock: load, drop the matching id (404 if none matched), write,
    return `204` (use `status_code=status.HTTP_204_NO_CONTENT` and return `None`).

### 2. `app/main.py`
- Add a `schedules_path: Path | None = None` parameter to `create_app(...)`.
- Set `application.state.schedules_path = schedules_path or SCHEDULES_PATH` (import `SCHEDULES_PATH`
  from `app.core.schedules`).
- `from app.api.schedules import router as schedules_router` and
  `application.include_router(schedules_router)`.

## Constraints / do-nots
- Touch ONLY `app/api/schedules.py` (new) and `app/main.py`. Do NOT edit any test,
  `app/core/schedules.py`, `app/core/scheduler.py`, the runner, or the frontend.
- Do NOT validate that `workflow_id` refers to a registered workflow — schedules are decoupled from
  the live registry (a due slot for an unknown workflow is the scheduler's skip to make). The contract
  does not register any workflow.
- Do NOT start runs, add a background timer, or thread `dry_run` anywhere — that is the later
  runner-wiring increment.
- No new dependencies (stdlib `uuid`/`threading`, FastAPI, Pydantic, and the existing model only).
- Keep `ruff check`, `ruff format --check`, and `mypy --strict` clean; match surrounding style;
  wrap at ≤100 columns.

## Scope
- `app/api/schedules.py`
- `app/main.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_schedules_api.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
