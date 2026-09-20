# TASK-Pb2 — MiniMax: send default ratio + duration

The P-B live smoke, after the `resolution` fix, showed MiniMax `/v2/video_generation` still 400s:
`"ratio is required for t2va (text-only) and cannot be 'adaptive'; allowed 16:9/4:3/1:1/3:4/9:16/21:9"`.
A frozen RED contract already fails: `tests/integration/test_provider_live_fixes.py::test_minimax_sends_default_ratio_and_duration`. Make it pass (and keep everything else green) by editing exactly one file.

## The fix — `sdk/sfvf/providers/minimax.py`

`generate_video` builds the submit body, sets `body["duration"]` only when `duration_s` is given, does `body.update(extra or {})`, then `body.setdefault("resolution", _DEFAULT_RESOLUTION)`. Add the two missing required/expected t2va params, both defaulted and overridable:

1. Add module constants next to `_DEFAULT_RESOLUTION`:
   - `_DEFAULT_RATIO = "16:9"`  (a valid documented value; allowed set 16:9/4:3/1:1/3:4/9:16/21:9)
   - `_DEFAULT_DURATION = 6`  (seconds; MiniMax H3 accepts 4–15)
2. After the existing `body.setdefault("resolution", _DEFAULT_RESOLUTION)` line, add:
   - `body.setdefault("ratio", _DEFAULT_RATIO)`
   - `body.setdefault("duration", _DEFAULT_DURATION)`
   `setdefault` means an explicit `extra["ratio"]`/`extra["duration"]`, or a provided `duration_s` (already placed into `body["duration"]` earlier), still wins; a default is present otherwise.
3. Align the reserve estimate so it matches the duration actually sent: in `video_estimate`, change the fallback `(duration_s or 5.0)` to `(duration_s or _DEFAULT_DURATION)`.

Nothing else changes — the poll, terminal-status, `task.content.url` extraction, download, and metered-cost reconcile from `task.usage` are all unchanged.

## Scope (ONLY this file)
- `sdk/sfvf/providers/minimax.py`

Do NOT touch any test, any other file, docs/, handoff/, requirements, or CI.

## Constraints
- No new dependency. Minimal change (minimal-code rule).
- `ruff check`, `ruff format --check`, and `mypy` clean on the file.

## Acceptance criteria
1. `python -m pytest tests/integration/test_provider_live_fixes.py` — all pass (the new ratio/duration test and the existing resolution test).
2. `python -m pytest tests/integration/test_video_minimax.py` — the frozen P-7 contract still passes.
3. `ruff check` + `ruff format --check` + `mypy` clean on `sdk/sfvf/providers/minimax.py`.
4. git diff shows exactly that one file changed.
