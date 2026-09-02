"""A-5 contract: `sfvf.media.graphics` composition stubs (SDK §6.5).

The composition provider (real: HyperFrames, Stage B) is stubbed here with FFmpeg:
`render` -> a colour-bars clip of the requested duration; `captions` -> a subtitle
file from the word timings; `safe_zone_css` -> a CSS file; `check` -> no violations.
File-producing results are video-relative path strings (JSON-native, so `render`
caches through `ctx.step`, per the A-3/A-4 pattern and SDK §5.5).
"""

import json
from pathlib import Path

import pytest
from sfvf import media
from sfvf._ffmpeg import probe
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


def test_render_dry_run_returns_video_relative_clip(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    token = set_active(_ctx(video_dir, dry_run=True))
    try:
        out = media.graphics.render("<h1>hi</h1>", duration_s=1.5)
    finally:
        reset_active(token)
    assert isinstance(out, str)
    json.dumps(out)  # JSON-native
    clip = _rel_file(video_dir, out)
    assert abs(probe(clip).duration_s - 1.5) < 0.2


def test_render_is_deterministic(tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    token = set_active(_ctx(a, dry_run=True))
    try:
        first = media.graphics.render("<h1>same</h1>", duration_s=2.0)
    finally:
        reset_active(token)
    token = set_active(_ctx(b, dry_run=True))
    try:
        second = media.graphics.render("<h1>same</h1>", duration_s=2.0)
    finally:
        reset_active(token)
    assert first == second


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


def test_render_hashing_has_no_ambiguous_collision(tmp_path: Path) -> None:
    # Distinct (html, duration_s) inputs must not collide onto one artifact. Naive
    # concatenation would make ("x1", 2.0) and ("x", 12.0) both key on "x12.0".
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    token = set_active(_ctx(video_dir, dry_run=True))
    try:
        first = media.graphics.render("x1", duration_s=2.0)
        second = media.graphics.render("x", duration_s=12.0)
    finally:
        reset_active(token)
    assert first != second


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


def test_render_non_dry_run_raises_not_implemented(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    token = set_active(_ctx(video_dir, dry_run=False))
    try:
        with pytest.raises(NotImplementedError):
            media.graphics.render("<h1>hi</h1>", duration_s=1.0)
    finally:
        reset_active(token)
