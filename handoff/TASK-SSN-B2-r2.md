# TASK-SSN-B2-r2 — Defensively coerce video_index (corrupt-ledger robustness)

The security review found that B2's new `int(entry.get("video_index", 0))` reads in `sdk/sfvf/_budget.py` (in `_token_states` and in `reconcile`) raise `TypeError` on a malformed non-absent value (e.g. `"video_index": null` in a hand-edited/corrupt ledger). `TypeError` is not caught by `_snapshot`'s guard nor by `read_run_spend`'s best-effort `except`, so it breaks the established contract that a corrupt ledger must NOT fail a finished run's record write. Fix ONLY `sdk/sfvf/_budget.py`. Make the supervisor-authored frozen test green without editing it:
- `tests/sdk/test_budget_per_video.py::test_malformed_video_index_does_not_break_read_run_spend` (currently RED)
Keep all other budget tests green (do NOT edit any test).

## Fix

- Add a tiny module-level helper, e.g. `def _int_or_zero(value: object) -> int:` that returns `int(value)` when it is safely coercible and `0` otherwise (catch `(TypeError, ValueError)`; a bool is fine as int). Use it in place of the two `int(entry.get("video_index", 0))` call sites (`_token_states` ~line 173, and `reconcile` ~line 418). An absent field still yields 0; a null/list/garbage value now yields 0 instead of raising. This mirrors how `meter`/`amount` are validated defensively elsewhere and preserves the corrupt-ledger best-effort contract for `read_run_spend` and the fail-closed behaviour of `reserve` (which still refuses on a corrupt ledger, now via a clean path rather than an uncaught TypeError).

Do not change any enforcement logic (the per-video ceiling, per_run/per_day, reserve/release). This is purely input-hardening of the video_index read.

## Scope

- sdk/sfvf/_budget.py

Do NOT modify: any test, other source, `docs/`, `handoff/`, dependencies.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/sdk/test_budget_per_video.py tests/sdk/test_ctx_per_video_budget.py tests/sdk/test_budget.py tests/sdk/test_budget_breach.py -q` passes.
- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/_budget.py` clean, `./.venv/Scripts/python.exe -m ruff format --check .` all formatted, project `./.venv/Scripts/python.exe -m mypy` clean (only the pre-existing PIL error).
- Print the file you changed and a one-line summary.
