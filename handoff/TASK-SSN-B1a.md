# TASK-SSN-B1a — Run-settings plumbing (backend): approval mode, per-video budget, voice

Thread three run-level settings, chosen at launch, from the HTTP launch body through admission and the supervisor into every video's `context.json`, and expose them on `ctx`. This is the backend half of Stage-B B1 (the frontend controls are a separate increment). Make the supervisor-authored frozen tests green WITHOUT editing them:
- `tests/api/test_run_settings_admit.py` (admit_run forwards the three to run_request)
- `tests/api/test_run_settings_api.py` (launch validates + persists them into context.json)
- `tests/sdk/test_context_run_settings.py` (ctx exposes them)

Keep every other existing test green (do NOT edit any test).

## The three settings

- `gates_auto: bool` — approval mode. Already a first-class ContextFile field and a run_request/admit_run param; it is simply not yet exposed on the HTTP LaunchBody.
- `per_video_budget: float | None` — the owner's per-video cost cap (read later by the B2 budget engine). `None` = no per-video cap. When set it must be `> 0` and within a sane maximum.
- `voice: str` — the narration voice id (resolved later by B4). `""` = the default voice. When non-empty it must be a path-safe id, optionally with a single `preset:` prefix.

## Part 1 — SDK (`sdk/sfvf/context.py`)

- Add two fields to `ContextFile` (alongside `gates_auto`, ~line 123): `per_video_budget: float | None = Field(default=None, description=...)` and `voice: str = Field(default="", description=...)`.
- Mirror them onto the `Context` object in `Context.__init__` next to `self.gates_auto = file.gates_auto` (~line 562): `self.per_video_budget = file.per_video_budget` and `self.voice = file.voice`.

## Part 2 — supervisor (`app/core/supervisor.py`)

- Add `per_video_budget: float | None = None` and `voice: str = ""` to the `_ContextWiring` dataclass (near `gates_auto`, ~line 97).
- `run_request(...)` gains params `per_video_budget: float | None = None` and `voice: str = ""`; store them into `_ContextWiring(...)` (~line 482-498).
- In the ContextFile builder `_make_context` (~line 272-299) pass `per_video_budget=wiring.per_video_budget` and `voice=wiring.voice` into `ContextFile(...)`, alongside the existing `gates_auto=wiring.gates_auto`.

## Part 3 — API (`app/api/runs.py`)

- `LaunchBody` gains `gates_auto: bool = False`, `per_video_budget: float | None = None`, `voice: str = ""`.
- Validation (return 422 on violation -- pydantic field validators are fine):
  - `per_video_budget`: when not None, must be `> 0` and `<= MAX_PER_VIDEO_BUDGET`. Define `MAX_PER_VIDEO_BUDGET = 1000.0` (a sane dollar ceiling well above the product's $8 per-video target; the $8 aggregate ceiling is enforced separately by B2 -- do NOT hardcode $8 here). `0`, negatives, and absurd values (e.g. 1e9) are rejected.
  - `voice`: when non-empty, must match `^(preset:)?[A-Za-z0-9._-]+$` -- i.e. an optional single `preset:` prefix then a path-safe token of letters/digits/dot/dash/underscore. Anything with a path separator (`/`, `\`), `..`, whitespace, or other punctuation is rejected. `""` is allowed (default voice).
- `admit_run(...)` gains `per_video_budget: float | None = None` and `voice: str = ""` params and forwards all three (it already has `gates_auto`) to `run_request` in its `target()` body.
- `launch_run(...)` passes `gates_auto=body.gates_auto`, `per_video_budget=body.per_video_budget`, `voice=body.voice` into the `admit_run(...)` call (it currently passes none of them).

## Scope

- sdk/sfvf/context.py
- app/core/supervisor.py
- app/api/runs.py

Do NOT modify: any test, `frontend/`, `docs/`, `handoff/`, dependencies. Do NOT run `npm run build`.

## Constraints

- Workspace boundary; ASCII in Python; one paragraph is one line in Markdown.
- This is security-relevant (untrusted launch input reaching a run + a path-shaped `voice` id); keep the validation strict and fail-closed. Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/api/test_run_settings_admit.py tests/api/test_run_settings_api.py tests/sdk/test_context_run_settings.py tests/api/test_runs.py tests/api/test_admit_run_dry_run.py tests/core/test_supervisor.py -q` passes; only the known pre-existing unrelated failures elsewhere.
- `./.venv/Scripts/python.exe -m ruff check app/api/runs.py app/core/supervisor.py sdk/sfvf/context.py` clean, `./.venv/Scripts/python.exe -m ruff format --check .` reports all formatted, and project `./.venv/Scripts/python.exe -m mypy` clean (only the pre-existing PIL error).
- Print the files you changed and a one-paragraph summary.
