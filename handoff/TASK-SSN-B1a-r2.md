# TASK-SSN-B1a-r2 — Reject non-finite per_video_budget and all-dots voice ids

The security review found one BLOCKING gap and one advisory in the B1a LaunchBody validators (`app/api/runs.py`). Fix ONLY `app/api/runs.py`. Make the supervisor-authored frozen tests green without editing them (they were extended for this round):
- `tests/api/test_run_settings_api.py::test_launch_rejects_nonfinite_per_video_budget` (NaN / Infinity / -Infinity, currently RED)
- `tests/api/test_run_settings_api.py::test_launch_rejects_unsafe_voice[.]` (a bare `.`, currently RED)
Keep all the other B1a tests green (do NOT edit any test).

## Defect 1 (BLOCKING) — non-finite per_video_budget slips through

`json.loads` accepts the bare `NaN` / `Infinity` / `-Infinity` literals and pydantic v2 allows non-finite floats by default, so a raw request body can set `per_video_budget` to a non-finite value. The current check `if value <= 0 or value > MAX_PER_VIDEO_BUDGET` passes NaN (both comparisons are False) and — over the real HTTP path — also lets Infinity/-Infinity through. A non-finite per-video cap defeats every later `spent > cap` comparison (the cap silently never trips).

- In `_per_video_budget_in_range`, reject any non-finite value: `import math` (module top) and, when `value is not None`, `if not math.isfinite(value): raise ValueError("per_video_budget must be a finite number")` BEFORE the range test. Keep the existing `> 0` / `<= MAX_PER_VIDEO_BUDGET` check for finite values.

## Defect 2 (advisory, fix now — same validator, cheap) — an all-dots voice id

The `voice` validator's `".." in value` guard misses a bare `.` (and any all-dots token), which passes the regex because `.` is in the character class. When B4 builds `assets/voices/<voice>`, a `.` segment resolves to the directory itself.

- In `_voice_path_safe`, after the existing `..` guard and regex check, also reject a token that is composed solely of `.` characters. Concretely: strip an optional leading `preset:` prefix, and if the remaining token is non-empty and consists only of `.` (i.e. it matches `^\.+$`), raise a ValueError. Keep the existing behaviour for all other values (e.g. `narrator`, `preset:calm`, `voice_2`, `a.b-c` stay valid).

## Note recorded for B4 (do NOT act on here)

A leading-dash voice id (e.g. `-rf`) currently passes and is harmless as a path segment, but B4 must never pass `voice` as a bare command-line argument to a TTS/subprocess (option-injection); B4 will pass it as a path component or after a `--` terminator. This is a B4 concern, not part of this fix.

## Scope

- app/api/runs.py

Do NOT modify: any test, other source, `docs/`, `handoff/`, dependencies.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/api/test_run_settings_api.py tests/api/test_run_settings_admit.py -q` passes (the non-finite and `.` cases included).
- `./.venv/Scripts/python.exe -m ruff check app/api/runs.py` clean, `./.venv/Scripts/python.exe -m ruff format --check .` all formatted, project `./.venv/Scripts/python.exe -m mypy` clean (only the pre-existing PIL error).
- Print the file you changed and a one-line summary.
