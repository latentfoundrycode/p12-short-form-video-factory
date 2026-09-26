# TASK-SSN-D1 — Vertically centre the caption composition

## Context

The Sensational Science News workflow inherited the `explainer`'s caption band, which is anchored to
the BOTTOM of the frame (`bottom:22%`). For this format the grouped, per-word-highlighted captions must
sit at the VERTICAL CENTRE of the 9:16 frame. This task re-centres them. The narration voice is already
wired correctly (`run()` passes `ctx.voice` to `media.speech.speak`) — do not change that.

## Scope — edit ONLY this file

- `workflows/sensational-science-news/main.py`

Change only the CSS in `_composition_html`. Do NOT change the caption grouping / word-timing JS, the
GSAP timeline, `run()`, `prepare()`, the SDK, or dependencies. Stay in this checkout.

## The frozen test to make green (do not edit it)

- `tests/integration/test_ssn_captions.py::test_composition_centers_captions` — asserts the
  composition is vertically centred (`translateY(-50%)` present, `50%` present) and no longer contains
  `bottom:22%`.
- `::test_run_speaks_in_the_chosen_voice` is already green (regression pin) — keep it green.

## What to change

In `_composition_html`'s `<style>` block, the two positioned caption elements are:

- `#captions { position:absolute; left:0; right:0; bottom:22%; display:flex; ... align-items:flex-end; ... }`
- `.cap-group { position:absolute; left:0; right:0; bottom:0; display:flex; ... align-items:flex-end; ... opacity:0; visibility:hidden; }`

Re-anchor BOTH to the vertical centre instead of the bottom:

- Replace `bottom:22%` on `#captions` with a vertical-centre anchor: `top:50%; bottom:auto;
  transform:translateY(-50%);`
- Replace `bottom:0` on `.cap-group` with the same vertical-centre anchor: `top:50%; bottom:auto;
  transform:translateY(-50%);`
- Change `align-items:flex-end` to `align-items:center` on both, so multi-line caption groups grow
  symmetrically about the centre line rather than upward from a baseline.

Keep everything else: `left:0; right:0`, `justify-content:center`, the `gap`, the `padding:0 162px`
safe-zone gutters, the `.cap-word`/`.bg` styles, the opacity/visibility animation, and all the GSAP
timeline JS. The result must still be one caption group visible at a time, highlighted per word, now
centred vertically.

## Done when (run from Workspace/ with the repo venv)

- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_captions.py -q` — both pass.
- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_workflow_dry_run.py -q` — still
  green (the dry-run pipeline still renders a finished 1080x1920 video with the centred captions).
- `./.venv/Scripts/python.exe -m ruff check workflows/sensational-science-news` and
  `./.venv/Scripts/python.exe -m ruff format --check .` — clean.
- `./.venv/Scripts/python.exe -m mypy` — no new errors from `main.py`.

Print the updated `#captions` and `.cap-group` rules.
