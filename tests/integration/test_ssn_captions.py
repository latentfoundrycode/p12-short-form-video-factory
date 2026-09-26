"""TASK-SSN-D1 contract: captions are vertically centered, and the chosen voice is honoured.

The C1 scaffold inherited the explainer's BOTTOM-anchored caption band (`bottom:22%`). For the
Sensational Science News format the grouped, per-word-highlighted captions sit at the VERTICAL
CENTRE of the 9:16 frame. The narration must also be spoken in the run's chosen voice (already
wired in C1; pinned here against regression).

Supervisor-authored (RED-first); the builder re-centres the caption composition in main.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths
from sfvf.gate import GateRejected

_WF = Path(__file__).resolve().parents[2] / "workflows" / "sensational-science-news"


def _load_main():
    spec = importlib.util.spec_from_file_location("ssn_main_captions_ut", _WF / "main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_TIMINGS = [
    {"word": "amazing", "start": 0.0, "end": 0.4},
    {"word": "science", "start": 0.4, "end": 0.9},
]


def test_composition_centers_captions() -> None:
    main = _load_main()
    html = main._composition_html("amazing science", _TIMINGS, "")  # css_path is ignored by the fn
    # vertically centred, not bottom-anchored like the inherited explainer band
    assert "translateY(-50%)" in html, "captions must be vertically centred"
    assert "50%" in html
    assert "bottom:22%" not in html and "bottom: 22%" not in html


class _StopBeforeRenderError(Exception):
    pass


def _run_ctx(tmp: Path, *, voice: str, subject: str) -> Context:
    (tmp / "01" / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp / "01" / ".steps").mkdir(parents=True, exist_ok=True)
    (tmp / "cache").mkdir(parents=True, exist_ok=True)
    return Context(
        ContextFile(
            settings={},
            dry_run=True,
            workflow_id="sensational-science-news",
            video_index=1,
            video_count=1,
            voice=voice,
            shared={"subjects": [subject], "sources": {subject: []}},
            paths=ContextPaths(
                video=tmp / "01",
                artifacts=tmp / "01" / "artifacts",
                steps=tmp / "01" / ".steps",
                shared=tmp / "01",
                cache=tmp / "cache",
                library=tmp / "lib",
            ),
        )
    )


def test_run_speaks_in_the_chosen_voice(tmp_path: Path, monkeypatch) -> None:
    # The run's chosen voice reaches media.speech.speak (regression pin for the C1 wiring).
    main = _load_main()
    ctx = _run_ctx(tmp_path, voice="preset:classic-male", subject="A finding")
    monkeypatch.setattr(
        main.agents, "llm", lambda prompt, *, agent, model, schema=None, attach=None: "A narration."
    )
    monkeypatch.setattr(ctx, "gate", lambda *a, **k: {"choice": "approve"})
    seen: dict[str, object] = {}

    def capture_speak(text, *, voice, model):
        seen["voice"] = voice
        raise _StopBeforeRenderError

    monkeypatch.setattr(main.media.speech, "speak", capture_speak)

    token = set_active(ctx)
    try:
        with pytest.raises((_StopBeforeRenderError, GateRejected)):
            main.run(ctx)
    finally:
        reset_active(token)
    assert seen.get("voice") == "preset:classic-male"
