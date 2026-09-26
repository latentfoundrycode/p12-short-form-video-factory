# TASK-SSN-D-fix2 — Correct the gate's vision-cost term (Review B round 2)

Review B confirmed the still/clip cost terms now match the reserve, and the redone-work blocker is
closed. One residual: the VISION cost in `_estimate_bed_cost` is wrong, so the gate can still sit below
the real reserve. Fix only that term.

## The bug

`media.web.source` performs up to `_WEB_CONSIDER` (24) PAID gpt-4o relevance checks per bed, each
reserving the owner's `openrouter` budget estimate. `_estimate_bed_cost` currently charges a flat
`_RELEVANCE_COST_USD` (0.03) once per static beat (`statics * (still_unit + _RELEVANCE_COST_USD)`),
which (a) ignores the owner's openrouter estimate and (b) counts `statics` checks, not the fan-out.
At an ordinary openrouter estimate ($0.05–0.10) the gate understates the reserve by $1–2.

## Scope — edit ONLY

- `workflows/sensational-science-news/main.py` (only `_estimate_bed_cost` + one constant).

## Frozen tests to make green (do not edit)

- `tests/integration/test_ssn_cost.py` — including
  `test_estimate_bed_cost_counts_openrouter_vision_reserve`,
  `test_estimate_bed_cost_uses_adapter_price_when_configured_is_lower`,
  `test_estimate_bed_cost_uses_configured_when_higher`.

## The fix

Add a constant `_OPENROUTER_METER = "openrouter"`.

In `_estimate_bed_cost`, compute the vision allowance for the whole bed (not per static beat) as the
fan-out times the per-check reserve, with the existing floor:
```python
vision_unit = max(ctx.budget_estimate(_OPENROUTER_METER) or 0.0, _RELEVANCE_COST_USD)
return round(clips * clip_unit + statics * still_unit + _WEB_CONSIDER * vision_unit, 2)
```
(i.e. replace `statics * (still_unit + _RELEVANCE_COST_USD)` with `statics * still_unit +
_WEB_CONSIDER * vision_unit`.) Keep `still_unit`/`clip_unit` exactly as they are (max of adapter price
and the configured estimate). Static beats are still all priced as paid AI stills (the conservative
commons-fails-worst-case), and the vision checks are now counted at the fan-out and the openrouter
reserve — so the gate figure is at or above the real reserve.

## Done when (run from Workspace/ with the repo venv)

- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_cost.py -q` — all pass.
- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_visual_bed.py tests/integration/test_ssn_assemble.py tests/sdk/test_media_price.py -q` — still green.
- `./.venv/Scripts/python.exe -m ruff check workflows/sensational-science-news` and `./.venv/Scripts/python.exe -m ruff format --check .` — clean.
- `./.venv/Scripts/python.exe -m mypy` — clean.

Print the updated `_estimate_bed_cost`.
