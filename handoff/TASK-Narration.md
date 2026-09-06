# TASK Narration — speak clean narration, not the LLM's stage directions

**Builder:** Cursor. **Product code only** in `workflows/explainer/main.py`. Do NOT touch `tests/`,
`docs/`, `handoff/`, the SDK. The reviewer contract `tests/integration/test_explainer_narration.py` is
FROZEN.

The explainer's `agents.llm("Write a … script on …")` returns a formatted script (scene directions in
`[…]`, speaker labels like `**Narrator (voice-over):**`, markdown, quoted VO). The workflow feeds that raw
text to `speak()` and the captions, so the narrator reads the directions aloud. Two changes:

## 1. Improve the script prompt (root cause)

Change the `agents.llm(...)` call in `run()` (currently `f"Write a {duration}-second script on {topic}."`)
to request ONLY the spoken words, e.g.:
`f"Write only the spoken narration for a {duration}-second short-form video about {topic}. Output plain "
`"sentences to be read aloud — no scene directions, no bracketed stage cues, no speaker labels or "
`"'voice-over', no markdown, no quotation marks. Just the words the narrator says."`
Keep `agent="scriptwriter"`, `model=_LLM_MODEL`.

## 2. Add a sanitizer `_narration_text` (safety net — models don't always obey)

Add a module-level function using `re` (stdlib):
```python
def _narration_text(raw: str) -> str:
    """Reduce an LLM 'script' to the words meant to be spoken: drop bracketed stage directions,
    markdown emphasis, speaker labels, and quotation marks; collapse whitespace."""
    text = re.sub(r"\[[^\]]*\]", " ", raw)                    # [Scene: …], [Cut …], [End …]
    text = re.sub(r"(?i)\b(?:narrator|voice[\s-]?over|vo|host|speaker)\b\s*(?:\([^)]*\))?\s*:",
                  " ", text)                                   # "Narrator (voice-over):", "Narrator:"
    text = re.sub(r"[*_]+", "", text)                         # markdown ** * __ _
    text = text.replace('"', " ").replace("“", " ").replace("”", " ")  # VO quotes
    return re.sub(r"\s+", " ", text).strip()
```
(Order matters: strip brackets first, then labels, then markdown, then quotes, then collapse. This must
leave clean prose essentially unchanged and yield `""` for empty/direction-only input.)

## 3. Apply it in `run()`

After the cached `script` step returns the raw LLM text, compute `narration = _narration_text(script)` and
use **narration** (not the raw script) for: the `speech` step input dict, the `media.speech.speak(...)`
call, `_composition_html(narration, …)`, and `_caption(narration)`. Keep the `script` step caching the raw
LLM output (so the paid call still caches); sanitize after it. So the audio, the timed captions, and the
Result caption all use the clean narration.

## Rules
Only `workflows/explainer/main.py`. `re` is stdlib; no new deps. ruff-clean; `workflows/` is outside mypy.

## Acceptance
`tests/integration/test_explainer_narration.py` passes (3): a messy script loses its brackets/labels/
markdown/quotes but keeps the spoken sentences with tidy whitespace; clean prose is unchanged;
empty/direction-only input yields `""`. The other explainer/composition tests still pass.

## Gate (from the worktree venv)
```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest -q tests/integration/test_explainer_narration.py tests/integration/test_explainer_composition.py
```
(The supervisor re-runs the real explainer afterward and listens/inspects that the narration is clean.)
