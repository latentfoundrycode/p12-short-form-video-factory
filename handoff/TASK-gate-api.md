# TASK — H-3: gate API (list pending gates + submit a shape-validated decision)

## Goal (one sentence)
Add two routes so the frontend can see which gates a run is waiting on and answer them: a `GET` that
lists pending gates and a `POST` that validates the user's decision against the gate's declared shape
and writes the response file the worker is polling.

## Background
A worker at `ctx.gate()` (H-1, merged) emits a `gate` event into the run's `events.jsonl` — via
`append_event(run_dir, event, source=<video dir>)` — and blocks polling
`run_dir/<video>/gates/<token>.json`. The gate event carries `t="gate"`, `family`, `token`, `shape`
(`"approval"|"choice"|"selection"`), `prompt`, and optionally `payload`/`options`/`items`/`on_bypass`.
`read_events(run_dir)` yields `(ts, source, event)`. A gate is **pending** iff its response file does
not exist. The CSRF middleware already guards the POST.

## Frozen contract (already committed — do NOT edit)
`tests/api/test_gate_api.py`. All existing tests must stay green.

## What to change — `app/api/runs.py` only
Add Pydantic models and two routes near the other `/runs/{run_id}` routes. Reuse the existing
helpers: `_require_workflow(request, workflow_id)`, `is_safe_path_segment`, `_runs_dir(request)`,
`read_events`, `format_video_dir`, and the app's atomic JSON writer `write_json_atomic` (as
`supervisor.py` uses it — import it the same way).

```python
class PendingGateOut(BaseModel):
    video: str
    video_index: int
    token: str
    family: str
    shape: str
    prompt: str
    payload: Any | None = None
    options: list[Any] | None = None
    items: list[Any] | None = None
    on_bypass: str | None = None

class GatesOut(BaseModel):
    gates: list[PendingGateOut]

class SubmitGateIn(BaseModel):
    video: str
    token: str
    decision: dict[str, Any]

class SubmitGateOut(BaseModel):
    ok: bool
```

### 1. `GET /workflows/{workflow_id}/runs/{run_id}/gates` -> `GatesOut`
- `_require_workflow`; `is_safe_path_segment(run_id)` else 404; `run_dir = _runs_dir/workflow_id/run_id`;
  404 if `not (run_dir / "request.json").is_file()`.
- Walk `read_events(run_dir)`; keep events with `event.get("t") == "gate"`. For each, `token =
  event["token"]`, `video = source`. Skip when `run_dir/<video>/gates/<token>.json` already exists
  (answered). De-duplicate by `(video, token)` keeping the last occurrence. `video_index = int(video)
  if video.isdigit() else 0`.
- Return the pending gates in first-seen order, echoing `family/shape/prompt` and the optional
  `payload/options/items/on_bypass` (use `event.get(...)`).

### 2. `POST /workflows/{workflow_id}/runs/{run_id}/gates` with `SubmitGateIn` -> `SubmitGateOut`
- `_require_workflow`; safe `run_id` (404) and run_dir exists (404).
- `HTTPException(400)` unless `is_safe_path_segment(body.video)`.
- Find the matching PENDING gate event: a `gate` event with `source == body.video` and
  `event["token"] == body.token` whose response file does NOT yet exist. If none → `HTTPException(404)`
  (this is the guard — only a real, still-open gate can be answered, so no arbitrary file write).
- **Validate `body.decision` against that gate's `shape`** (`HTTPException(400)` on any failure):
  - `decision` must be a dict with a string `"choice"`.
  - `approval`: `choice in {"approve", "reject"}`.
  - `choice`: `choice in event["options"]`.
  - `selection`: `choice in {"approve", "reject"}`; when `choice == "approve"`, `keep` and `redo`
    (each optional, default `[]`) must be lists of strings, every element a declared item id
    (`{it["id"] for it in event["items"]}`), and `keep`/`redo` disjoint. `note` optional string.
- Defence in depth: `live = run_dir / body.video / "gates" / f"{body.token}.json"`; require
  `live.resolve()` is within `(run_dir / body.video).resolve()`. Write `body.decision` with
  `write_json_atomic(live, body.decision)` (it creates the `gates/` parent). Return `SubmitGateOut(ok=True)`.

## Constraints / do-nots
- Touch ONLY `app/api/runs.py`. Do NOT edit any test or other file.
- Never write outside `run_dir/<video>/gates/`. The safe-segment check + the pending-gate match +
  the resolved-containment check are all required.
- Keep `ruff check .`, `ruff format --check .`, `mypy sdk app` clean; ≤100 cols.

## Review follow-up (SECOND delegation — four hardening fixes in `app/api/runs.py`)
Cross-family + security review found four edges on this user-input write path. Apply all four; new
frozen tests pin them.

1. **Tolerate a malformed `gate` event (both routes).** GET currently does `event["token"]` etc., so a
   workflow emitting a raw `{"t": "gate"}` (via `ctx.emit`) crashes the listing with a 500 and hides
   every valid gate. In BOTH the GET loop and the POST matching loop, read the fields with `.get(...)`
   and SKIP a gate event that is not a well-formed dict with string `token`, `family`, `shape`, and
   `prompt` (and a str `source`). Never raise on a malformed event.

2. **Refuse a traversal `token` + tighten the write containment to `gates/`.** Add
   `if not is_safe_path_segment(body.token): raise HTTPException(400)` alongside the `body.video`
   check. Change the containment base from the video dir to the gates dir:
   `if not live.resolve().is_relative_to((run_dir / body.video / "gates").resolve()): raise
   HTTPException(400)`.

3. **Redact secrets in the written decision.** Per the standing rule "redact on every write path":
   before writing, redact the decision — `secret_values = frozenset(v for v in
   _secrets(request).values() if v)` (the helper already imported in this module) and
   `_redact_secrets(body.decision, secret_values)` (import `_redact_secrets` from
   `app.core.supervisor`, as `app/api/learning.py` does). Write the REDACTED decision.

4. **Write only the validated keys (strict boundary).** Build the persisted decision from the fields
   you validated, dropping any extra client keys, and reject a contradictory selection reject:
   - approval / choice: write `{"choice": choice}` plus `{"note": <str>}` only if `decision` has a
     string `note`.
   - selection `reject`: write `{"choice": "reject"}` plus a string `note` if present — and 400 if the
     client sent a non-empty `keep` or `redo` with a reject (contradictory).
   - selection `approve`: write `{"choice": "approve", "keep": [...], "redo": [...], "note": <str or
     "">}` from the validated lists.
   Then redact THAT normalized dict (per #3) and `write_json_atomic` it.

(Deliberately NOT fixed: the concurrent double-answer TOCTOU — single-user local tool, the write is
idempotent-ish and the worker consumes whatever is present on its next poll. Accepted.)

Keep everything else. Touch ONLY `app/api/runs.py`. Keep lint/format/mypy clean.

## Scope
- `app/api/runs.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_gate_api.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
