"""`sfvf.media.graphics` — the non-render surface (captions, safe_zone_css, check).

`render` is exercised separately in tests/integration/test_graphics_render.py, and `check` in
tests/integration/test_composition_check.py, since as of B-1b/E-2a they drive the HyperFrames
toolchain (SDK §6.5). The functions here need no toolchain: `captions` writes an SRT from the
word timings, `safe_zone_css` writes the PRD safe-zone CSS. File-producing results are
video-relative path strings (JSON-native, per SDK §5.5).
"""

import json
from pathlib import Path

import pytest
from sfvf import media
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths


def _ctx(video_dir: Path, *, dry_run: bool) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            paths=ContextPaths(
                video=video_dir,
                artifacts=video_dir / "artifacts",
                steps=video_dir / ".steps",
                shared=video_dir,
            ),
        )
    )


def _rel_file(video_dir: Path, rel: str) -> Path:
    assert isinstance(rel, str)
    assert not Path(rel).is_absolute()
    target = video_dir / rel
    assert target.is_file()
    return target


def test_graphics_require_an_active_context() -> None:
    with pytest.raises(RuntimeError):
        media.graphics.render("<html></html>", duration_s=2.0)


def test_captions_dry_run_returns_video_relative_file(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    timings = [
        {"word": "one", "start": 0.0, "end": 0.5},
        {"word": "two", "start": 0.5, "end": 1.0},
    ]
    token = set_active(_ctx(video_dir, dry_run=True))
    try:
        out = media.graphics.captions("artifacts/narration.m4a", timings, "bold")
    finally:
        reset_active(token)
    assert isinstance(out, str)
    json.dumps(out)
    _rel_file(video_dir, out)


def test_captions_real_mode_writes_srt(tmp_path: Path) -> None:
    # captions is toolchain-free (an SRT built from the word timings), so it must work in REAL mode
    # too — the explainer's real end-to-end run calls it after live synthesis + alignment.
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    timings = [
        {"word": "one", "start": 0.0, "end": 0.5},
        {"word": "two", "start": 0.5, "end": 1.0},
    ]
    token = set_active(_ctx(video_dir, dry_run=False))
    try:
        out = media.graphics.captions("artifacts/narration.m4a", timings, "bold")
    finally:
        reset_active(token)
    assert isinstance(out, str)
    assert out.endswith(".srt")
    text = _rel_file(video_dir, out).read_text(encoding="utf-8")
    assert "one" in text and "two" in text
    assert "-->" in text  # SRT cue timing line


def test_safe_zone_css_uses_prd_margins(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    token = set_active(_ctx(video_dir, dry_run=True))
    try:
        out = media.graphics.safe_zone_css()
    finally:
        reset_active(token)
    assert isinstance(out, str)
    css = _rel_file(video_dir, out).read_text(encoding="utf-8")
    # PRD: the reserved regions are the top 10%, the right 15%, and the bottom 15%.
    assert "padding-top: 10%" in css
    assert "padding-right: 15%" in css
    assert "padding-bottom: 15%" in css


# `check()` is a real headless-DOM inspection as of E-2a; its behavior (the four §6.5 checks,
# a clean composition returning [], JSON-native violations) is covered in the toolchain-gated
# tests/integration/test_composition_check.py. The A-5 dry-run no-op stub test is retired here.


# --- _parse_violations: robust against the Node stderr that `_run` merges into stdout ---
# `_run` sets stderr=STDOUT, so a Node deprecation/experimental warning (which contains
# brackets, e.g. "(node:1) [DEP0040] DeprecationWarning") can precede the JSON on the merged
# stream. A greedy first-"["/last-"]" slice would then fail to parse and RuntimeError on an
# otherwise-clean composition — which E-2b would turn into a false-failed paid render. Parsing
# must key on the JSON array line the script actually prints last.


def test_parse_violations_ignores_leading_node_stderr_noise() -> None:
    from sfvf.media.graphics import _parse_violations

    raw = "(node:1234) [DEP0040] DeprecationWarning: punycode is deprecated\n[]\n"
    assert _parse_violations(raw) == []


def test_parse_violations_reads_the_json_array_after_noise() -> None:
    from sfvf.media.graphics import _parse_violations

    raw = (
        "[ExperimentalWarning] VM Modules is experimental\n"
        '[{"kind": "safe-zone", "detail": "h1 intersects the reserved safe zone"}]\n'
    )
    assert _parse_violations(raw) == [
        {"kind": "safe-zone", "detail": "h1 intersects the reserved safe zone"}
    ]


def test_parse_violations_raises_when_no_json_array_present() -> None:
    from sfvf.media.graphics import _parse_violations

    with pytest.raises(RuntimeError):
        _parse_violations("some fatal error text\nno array here\n")
