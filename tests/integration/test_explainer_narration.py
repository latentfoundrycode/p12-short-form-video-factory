"""Narration contract: the explainer speaks clean narration, not the LLM's stage directions.

`agents.llm("write a script …")` returns a formatted script — scene directions in brackets, speaker
labels like Narrator voice-over, markdown emphasis, quoted VO. The first real video fed that raw
text straight to TTS, so the narrator read the directions aloud. `_narration_text` strips that
scaffolding to the words actually meant to be spoken (a safety net beneath the improved prompt); the
explainer applies it before `speak()` so both the audio and the timed captions are clean.

Loaded by path — the explainer is not an importable package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MAIN = Path(__file__).resolve().parents[2] / "workflows" / "explainer" / "main.py"


def _narration():
    spec = importlib.util.spec_from_file_location("_explainer_main_narr", _MAIN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._narration_text


_MESSY = (
    "[Scene: Bright, sunny garden with plants swaying] **Narrator (voice-over):** "
    '"Photosynthesis is the process plants use to make food." [Cut to a close-up of a leaf] '
    '**Narrator:** "It starts with sunlight." [End scene with a bright sun]'
)


def test_narration_strips_directions_labels_and_markdown() -> None:
    out = _narration()(_MESSY)
    # scaffolding gone
    assert "[" not in out and "]" not in out  # bracketed stage directions
    assert "*" not in out  # markdown emphasis
    assert "narrator" not in out.lower()  # speaker labels
    assert "voice-over" not in out.lower() and "voice over" not in out.lower()
    assert '"' not in out and "“" not in out and "”" not in out  # VO quotes
    # the actual spoken words survive
    assert "Photosynthesis is the process" in out
    assert "It starts with sunlight" in out
    # tidy whitespace (no double spaces, trimmed)
    assert "  " not in out
    assert out == out.strip()


def test_narration_leaves_clean_prose_essentially_unchanged() -> None:
    clean = "Photosynthesis turns sunlight into chemical energy inside a leaf."
    assert _narration()(clean) == clean


def test_narration_empty_is_safe() -> None:
    assert _narration()("") == ""
    assert _narration()("   [only a direction]   ") == ""
