"""TASK-SSN-D3a contract: composite the visual bed behind the centered captions (approach a).

`_composition_html(script, timings, css_path, bed)` now renders the D2 visual bed BEHIND the
captions in one HyperFrames composition: each static image (web/still) is an `<img>` with a
KEN-BURNS pan/zoom driven by the SAME GSAP timeline as the captions (a wall-clock CSS animation
would not be captured by the seek-based renderer, nor generate inter-frame motion), and each clip
is a `<video>` timed to its beat. The Ken-Burns motion must be strong enough that a real render is
NOT a slideshow: `_review.content_review` records a `slideshow` verdict when the scdet inter-frame
motion score is too low. A NON-DRY mini-render over a textured fixture must clear that verdict (the
rev-5 pre-spend checkpoint — the recorded signal, not a hard finalize gate, which the SDK defers).

Supervisor-authored (RED-first); the builder extends `_composition_html` + `run()` in main.py.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths

_WF = Path(__file__).resolve().parents[2] / "workflows" / "sensational-science-news"


def _load_main():
    spec = importlib.util.spec_from_file_location("ssn_main_composite_ut", _WF / "main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_TIMINGS = [
    {"word": "amazing", "start": 0.0, "end": 0.5},
    {"word": "science", "start": 0.5, "end": 1.0},
]


def test_composition_includes_visual_bed() -> None:
    main = _load_main()
    bed = {
        "assets": [
            {
                "kind": "still",
                "path": "artifacts/still0.png",
                "start": 0.0,
                "end": 1.5,
                "url": None,
                "ken_burns": True,
            },
            {
                "kind": "clip",
                "path": "artifacts/clip0.mp4",
                "start": 1.5,
                "end": 3.0,
                "url": None,
                "ken_burns": False,
            },
        ],
        "source_urls": [],
    }
    html = main._composition_html("amazing science", _TIMINGS, "", bed)
    # both bed assets are placed in the composition
    assert "artifacts/still0.png" in html
    assert "artifacts/clip0.mp4" in html
    # the clip is a real <video> element (HyperFrames extracts its frames)
    assert "<video" in html
    # the static image gets a GSAP-driven Ken-Burns scale (so it is captured + generates motion)
    assert "scale" in html
    # captions still present and drawn ABOVE the bed
    assert "cap-group" in html


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        pytest.skip("ffmpeg not on PATH")
    return exe


def _nondry_ctx(tmp: Path) -> Context:
    (tmp / "01" / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp / "01" / ".steps").mkdir(parents=True, exist_ok=True)
    (tmp / "cache").mkdir(parents=True, exist_ok=True)
    return Context(
        ContextFile(
            settings={},
            dry_run=False,
            workflow_id="sensational-science-news",
            video_index=1,
            video_count=1,
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


def test_nondry_kenburns_clears_slideshow(tmp_path: Path) -> None:
    # The rev-5 pre-spend checkpoint: a REAL render of a Ken-Burns still (textured fixture) must NOT
    # be judged a slideshow by _review.content_review (motion_score >= SLIDESHOW_MOTION_MIN).
    from sfvf import _review, media

    main = _load_main()
    if shutil.which("node") is None:
        pytest.skip("node (HyperFrames) not on PATH")
    ffmpeg = _ffmpeg()
    ctx = _nondry_ctx(tmp_path)
    fixture = ctx.paths.artifacts / "kbfix.png"
    # a TEXTURED frame so a pan/zoom produces real inter-frame change (a solid colour would not)
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1080x1920:duration=1",
            "-frames:v",
            "1",
            str(fixture),
        ],
        check=True,
    )
    bed = {
        "assets": [
            {
                "kind": "still",
                "path": "artifacts/kbfix.png",
                "start": 0.0,
                "end": 3.0,
                "url": None,
                "ken_burns": True,
            }
        ],
        "source_urls": [],
    }
    html = main._composition_html("hello world", _TIMINGS, "", bed)
    token = set_active(ctx)
    try:
        rel = media.graphics.render(html, duration_s=3.0)
        review = _review.content_review((ctx.paths.video / rel).resolve(), expect_audio=False)
    finally:
        reset_active(token)
    assert review.slideshow is False, f"Ken-Burns motion too weak: {review}"
    assert review.black is False
