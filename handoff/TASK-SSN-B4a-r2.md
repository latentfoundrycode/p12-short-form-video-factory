# TASK-SSN-B4a-r2 — Restore the owner-approved denoise noise floor (nf=-30)

Review A found the `_denoise` filter in `sdk/sfvf/media/speech.py` uses `afftdn=nr=12:nf=-25`, but the owner A/B-verified the GENTLE setting `nf=-30`. A higher floor (`-25`) denoises more aggressively, toward the muffling the owner rejected. Fix ONLY `sdk/sfvf/media/speech.py`. Make the supervisor-authored frozen test green without editing it: `tests/sdk/test_speech_voices.py::test_denoise_uses_the_owner_approved_gentle_filter` (currently RED; it pins the exact `-af` string). Keep all other speech tests green.

## Fix

In `_denoise`, change the ffmpeg `-af` value from `highpass=f=70,afftdn=nr=12:nf=-25` to exactly:
`highpass=f=70,afftdn=nr=12:nf=-30`
Nothing else changes.

## Scope

- sdk/sfvf/media/speech.py

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/sdk/test_speech_voices.py tests/sdk/test_speech.py -q` passes.
- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/media/speech.py` and `./.venv/Scripts/python.exe -m ruff format --check .` clean.
- Print the one-line change made.
