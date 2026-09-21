# TASK — web-sourcing inc4: check_relevance (the VLM relevance gate)

## Context
`sdk/sfvf/media/web.py::check_relevance(image, *, subject, model=_VISION_MODEL) -> Relevance` currently
returns a passing stub in dry-run and raises `NotImplementedError` on the real path. Build the real
path (docs/DESIGN §3.1): show the image to a vision model and return whether it depicts `subject`.
`Relevance` is the existing TypedDict `{relevant: bool, score: float, reason: str}`. A frozen RED
contract is committed: `tests/integration/test_media_web_relevance.py` (do not edit it).

## Scope
- **Edit ONLY** `sdk/sfvf/media/web.py`, function `check_relevance` (the real, non-dry-run path).
- Do NOT change the dry-run branch (it already returns the passing stub and must stay). No test edits,
  no new files, no new dependencies.

## Required behaviour (real path, `not ctx.dry_run`)
Call the SFVF vision surface — `agents.llm` with the image attached and a JSON schema — and map its
verdict onto `Relevance`, coercing/clamping the untrusted model output:

1. Import agents lazily inside the function: `from sfvf import agents` (keeps module import light and
   makes the call patchable in tests). Do NOT import it at module top.
2. Build a JSON schema requesting an object with properties `relevant` (boolean), `score` (number),
   `reason` (string), all required — e.g.:
   ```
   schema = {
       "type": "object",
       "properties": {
           "relevant": {"type": "boolean"},
           "score": {"type": "number"},
           "reason": {"type": "string"},
       },
       "required": ["relevant", "score", "reason"],
       "additionalProperties": False,  # REQUIRED: agents.llm sets strict=True; OpenAI 400s without it
   }
   ```
3. Build a prompt that puts `subject` to the model and asks it to judge whether the image depicts it,
   returning the relevant/score/reason verdict. The prompt MUST contain the `subject` text verbatim.
   Example: `f"Assess whether this image depicts the following subject.\nSubject: {subject}\nReturn "
   f"relevant (does it depict the subject), score (0.0-1.0 confidence it matches), and a brief reason."`
4. Call `result = agents.llm(prompt, agent="image-relevance", model=model, attach=[image], schema=schema)`.
   `attach` must be exactly `[image]` (only that one image). `model` is the function's `model` parameter
   (defaults to `_VISION_MODEL`; forward any override unchanged). `agent` is a fixed non-empty label
   (e.g. `"image-relevance"`).
5. `agents.llm` with a schema returns a `dict`. Map it onto `Relevance`, treating the values as
   UNTRUSTED model output:
   - `relevant = bool(result["relevant"])`
   - `score = float(result["score"])`, then CLAMP to `[0.0, 1.0]`: `min(1.0, max(0.0, score))`
   - `reason = str(result["reason"])`
   Return `Relevance(relevant=..., score=..., reason=...)`.

Leave `search`, `fetch`, `source`, and the dry-run branches unchanged.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_relevance.py tests/integration/test_media_web_surface.py -q`
  → **all pass** (11 relevance cases incl. the score-clamp parametrization and type coercion; surface unchanged).
- `python -m ruff format --check sdk/sfvf/media/web.py` and `python -m ruff check sdk/sfvf/media/web.py` → clean.
- `PYTHONPATH=sdk python -m mypy sdk/sfvf/media/web.py` → clean.
- `git diff --name-only` shows **only** `sdk/sfvf/media/web.py`.
