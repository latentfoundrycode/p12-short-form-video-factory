# TASK-SSN-D3c — Real approve-plan cost estimate (H-SSN-17) + URL control-char hardening

## Context

The approval gate runs BEFORE the paid media, so its `estimated_cost_usd` must be a real figure the
owner can judge, not the current `0.0` placeholder (H-SSN-17). Estimate the visual bed's cost from the
script. Also close a D3b security advisory: drop URLs carrying control characters in
`_sanitize_source_urls`.

## Scope — edit ONLY this file

- `workflows/sensational-science-news/main.py`

No new imports. Do not touch tests, SDK, other workflows, or deps. Stay in this checkout.

## Frozen tests to make green (read them first)

- `tests/integration/test_ssn_cost.py` (4 tests): `_estimate_bed_cost` pricing + zero-without-budget,
  control-char URL dropping, and the gate payload carrying the estimate.
- Keep `tests/integration/test_ssn_assemble.py`, `test_ssn_gate.py`, `test_ssn_workflow_dry_run.py`
  green.

## What to build

### 1. Constants

```python
_WORDS_PER_SEC = 2.5
_IMAGE_METER = "google"    # provider meter for _IMAGE_MODEL (google/gemini-3.1-flash-image)
_CLIP_METER = "byteplus"   # provider meter for _CLIP_MODEL (byteplus/seedance-2.5)
```

### 2. `_estimate_bed_cost(ctx, narration: str) -> float`

Estimate the paid visual-bed cost the approve-plan gate will show, from the script alone (the bed is
sourced only AFTER the gate):
- `words = len(narration.split())`; `duration = words / _WORDS_PER_SEC`.
- `beats = max(1, round(duration / _BEAT_S))` (same beat cadence as `_beats`).
- `clips = 2 if beats >= 4 else 1`, capped at `_MAX_CLIPS` (mirrors `_source_visual_bed`'s clip
  selection: beat 0 + last when >= 4 beats).
- `statics = max(0, beats - clips)`.
- `still_price = ctx.budget_estimate(_IMAGE_METER) or 0.0`;
  `clip_price = ctx.budget_estimate(_CLIP_METER) or 0.0`.
- Price EVERY static beat as an AI still (conservative worst case — some may turn out to be free
  commons images; overestimating the spend the owner approves is the safe direction). Add a one-line
  comment saying so.
- `return round(statics * still_price + clips * clip_price, 2)`.

### 3. Wire it into the gate

In `run()`, replace `estimated_cost = 0.0` with
`estimated_cost = _estimate_bed_cost(ctx, narration)` (the gate call and its payload otherwise
unchanged). `narration` is already computed just above the gate.

### 4. Harden `_sanitize_source_urls` (D3b security advisory)

After the `str(url).strip()` and BEFORE (or alongside) the scheme check, also DROP any URL that is not
fully printable (contains control characters such as `\r`, `\n`, `\t`): add
`if not s.isprintable(): continue`. This keeps a control-char-laced URL from injecting an extra line
into the description and makes the guarantee robust to a future richer sink. (Normal URLs are
printable; a legitimate space would be percent-encoded.)

## Done when (run from Workspace/ with the repo venv)

- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_cost.py tests/integration/test_ssn_assemble.py tests/integration/test_ssn_gate.py -q` — all pass.
- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_workflow_dry_run.py -q` — still green.
- `./.venv/Scripts/python.exe -m ruff check workflows/sensational-science-news` and
  `./.venv/Scripts/python.exe -m ruff format --check .` — clean.
- `./.venv/Scripts/python.exe -m mypy` — clean.

Print `_estimate_bed_cost`, the updated gate line, and the hardened `_sanitize_source_urls`.
