"""`sfvf.media.graphics` — the non-render surface (captions, safe_zone_css, check).

`render` is exercised separately in tests/integration/test_graphics_render.py, since as of
B-1b it renders real composed video via the HyperFrames toolchain (SDK §6.5). The functions
here need no toolchain: `captions` writes an SRT from the word timings, `safe_zone_css`
writes the PRD safe-zone CSS, `check` reports no violations in dry-run. File-producing
results are video-relative path strings (JSON-native, per SDK §5.5).
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


def test_check_dry_run_reports_no_violations(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    token = set_active(_ctx(video_dir, dry_run=True))
    try:
        violations = media.graphics.check("<h1>hi</h1>")
    finally:
        reset_active(token)
    assert violations == []
    json.dumps(violations)  # JSON-native
