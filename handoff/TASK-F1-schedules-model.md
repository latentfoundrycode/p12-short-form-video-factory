# TASK F-1 — schedule-entry model + schedules.json persistence (§5.7)

## Goal (one sentence)
Create `app/core/schedules.py` with a validated `ScheduleEntry` model and read/write of a
`schedules.json` list, the data layer the F-2 scheduler engine and F-3 API build on.

## Governing spec (verbatim — Architecture §5.7)
> Reads `schedules.json`. When an entry is due it checks two conditions and acts accordingly: if that
> workflow already has an active run, the slot is skipped; if the budget is insufficient, the slot is
> skipped. Otherwise the Generation Request starts with the saved settings. … Each entry carries the
> flag determining whether approval gates pause or pass automatically.

Owner decision (2026-09-12): scheduled runs default to a free **dry run**; real (paid) spend is a
per-entry opt-in that is **off by default** (F-2 will map `dry_run = not allow_real_spend`). So the
model carries `allow_real_spend` defaulting to `False`. This increment is DATA-ONLY: no scheduler
loop, no API, no runs started.

## Frozen contract (already committed — do NOT edit)
`tests/core/test_schedules.py`. It imports and pins this exact surface from `app.core.schedules`:
- `class ScheduleEntry` (a Pydantic model; forbid extra fields, like `_RecordModel` in
  `app/core/records.py`).
- `class ScheduleError(Exception)`.
- `read_schedules(path: Path) -> list[ScheduleEntry]`.
- `write_schedules(path: Path, entries: list[ScheduleEntry]) -> None`.

## What to implement (`app/core/schedules.py` only)

### `ScheduleEntry` fields + validation
- `id: str` — a stable identifier for CRUD. Must satisfy `app.paths.is_safe_path_segment` (reject
  `../escape`, `a/b`, `..`, `.`).
- `workflow_id: str` — same `is_safe_path_segment` validation.
- `days: list[int]` — weekday indices the slot fires on, Monday=0 … Sunday=6. Non-empty; every
  element in 0..6 (reject `[]`, `[7]`, `[-1]`, `[0, 7]`).
- `time_of_day: str` — 24-hour `"HH:MM"`, zero-padded. Accept `"07:00"`, `"23:59"`; reject `"25:00"`,
  `"7:00"`, `"07:60"`, `"0700"`, `"24:00"`, `"abc"`, `""`. (A regex like `^([01]\d|2[0-3]):[0-5]\d$`.)
- `video_count: int` — `>= 1`.
- `concurrency: int` — `>= 1`, default `1`.
- `params: dict[str, Any]` — the saved run settings (workflow params). Default empty dict is fine;
  the test always supplies one.
- `gates_auto: bool` — §5.7's approval-gate flag (True = gates pass automatically; False = pause).
- `allow_real_spend: bool` — default `False` (owner decision).
- Configure the model to FORBID extra fields (a stray key must raise `ValidationError`).

Use Pydantic v2 (`field_validator`/`Field(ge=…)`), matching the style of `app/core/records.py`
(which uses a `_RecordModel` base with `ConfigDict(extra="forbid")`) and `sfvf.context` models.

### Persistence
- `read_schedules(path)`: a missing file returns `[]`. A present file must be a JSON **list** of
  entry objects → return `[ScheduleEntry.model_validate(x) for x in list]`. Malformed JSON, a
  non-list top-level payload, or an entry that fails validation → raise `ScheduleError` (fail
  visibly; do not silently drop schedules). Read UTF-8.
- `write_schedules(path, entries)`: serialize the entries to a JSON list and write **atomically**
  (reuse `app.core.records.write_json_atomic` — note it takes a `Mapping`; you may write via a small
  atomic helper of the same shape for a top-level JSON *array*, or wrap as needed — the key
  requirement is an atomic temp-file-then-rename write, UTF-8, `ensure_ascii=False`, trailing
  newline, mirroring `write_json_atomic`). A `write_schedules` then `read_schedules` must round-trip
  to equal `ScheduleEntry` objects.
- Add a module-level default path constant `SCHEDULES_PATH = APP_ROOT / "schedules.json"` (from
  `app.paths`) for later increments; the functions take an explicit `path` (do not hardcode it).

## Constraints / do-nots
- Only create `app/core/schedules.py`. Do NOT edit any test, `app/core/records.py`, `app/paths.py`,
  the supervisor, or any API/frontend. Do NOT add a dependency (pydantic + stdlib only). Do NOT
  build the scheduler loop, the API, or start any run — those are F-2/F-3.
- Keep `ruff check`, `ruff format`, and `mypy --strict` clean; match the surrounding style.

## Scope
- `app/core/schedules.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_schedules.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
