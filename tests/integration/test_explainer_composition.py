"""Composition contract: the explainer's on-screen caption composition is legible + word-timed.

The first real end-to-end video rendered dark-grey text on near-black (unreadable) and dumped the
whole script statically. This pins the reworked `_composition_html`: a HyperFrames caption
composition that (a) is high-contrast and uses a real webfont, (b) renders each spoken word timed to
the narration (word text + its start/end) on the `main` GSAP timeline HyperFrames drives, and
(c) HTML-escapes the model-authored word text (never inject raw LLM output into markup).

`_composition_html` is a fragment embedded in `_index_html`'s `#root` (which creates the `main`
timeline and sets `data-composition-id="main"`), so the composition registers under "main".
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MAIN = Path(__file__).resolve().parents[2] / "workflows" / "explainer" / "main.py"


def _load_composition():
    spec = importlib.util.spec_from_file_location("_explainer_main", _MAIN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._composition_html


_TIMINGS = [
    {"word": "Photosynthesis", "start": 0.10, "end": 0.85},
    {"word": "turns", "start": 0.95, "end": 1.19},
    {"word": "sunlight", "start": 1.23, "end": 1.69},
    {"word": "into", "start": 1.77, "end": 1.91},
    {"word": "energy", "start": 2.37, "end": 2.72},
]


def test_composition_is_legible_and_word_timed() -> None:
    html = _load_composition()("the full narration script", _TIMINGS, "safe-zone.css")
    assert isinstance(html, str)

    # (a) every spoken word appears on screen, with its timing available to the animation
    for t in _TIMINGS:
        assert t["word"] in html
        assert str(t["start"]) in html
        assert str(t["end"]) in html

    # (b) drives the "main" GSAP timeline HyperFrames seeks (matches _index_html's composition id)
    assert 'window.__timelines["main"]' in html or "window.__timelines['main']" in html
    assert "gsap.timeline" in html

    # (c) high contrast: an explicit light text color, not the black-on-near-black default that
    #     produced the unreadable first render.
    lowered = html.lower()
    assert "#fff" in lowered or "#ffffff" in lowered or "rgb(255" in lowered or "white" in lowered

    # (d) a real, legible webfont is loaded (not the bare default sans-serif)
    assert "fonts.googleapis.com" in html or "@font-face" in html


def test_composition_escapes_model_authored_words() -> None:
    # Word text comes from the LLM/alignment — it must be HTML-escaped, never injected raw.
    danger = [{"word": "<script>alert(1)</script>", "start": 0.0, "end": 0.5}]
    html = _load_composition()("s", danger, "safe-zone.css")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_composition_handles_empty_timings() -> None:
    # No timings (edge) must not crash and must still produce a valid fragment string.
    html = _load_composition()("s", [], "safe-zone.css")
    assert isinstance(html, str)
    assert "gsap.timeline" in html
