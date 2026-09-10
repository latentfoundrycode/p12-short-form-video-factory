"""E-1 contract: content self-review (Architecture §5.8, SDK §6.9).

`content_review` measures a finished video with FFmpeg — black/broken frames, silent or clipping
audio, and a slideshow (too little inter-frame change) — the failures a valid file can still hide.
`finalize` runs it on a REAL run and fails the video on any failure; a dry run skips it (stub assets
are static/silent by construction). Fixtures are generated with FFmpeg lavfi sources; no real spend.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sfvf
from sfvf._ffmpeg import _binary, _run
from sfvf._review import content_review
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths

_MOVING = "testsrc2=size=320x240:rate=30"
_BLACK = "color=c=black:s=320x240:r=30"
_STATIC = "color=c=gray:s=320x240:r=30"
_SILENT = "anullsrc=channel_layout=stereo:sample_rate=44100"
_NORMAL_AUDIO = "sine=frequency=440:sample_rate=44100,volume=0.3"
_CLIPPING_AUDIO = "sine=frequency=440:sample_rate=44100,volume=8"


def _clip(path: Path, *, video: str, audio: str | None = None, dur: float = 1.0) -> Path:
    """Generate a small clip from FFmpeg lavfi sources (no real assets)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [_binary("ffmpeg"), "-y", "-fflags", "+bitexact", "-f", "lavfi", "-i", video]
    if audio is not None:
        command += ["-f", "lavfi", "-i", audio, "-c:a", "aac", "-shortest"]
    command += ["-t", str(dur), "-pix_fmt", "yuv420p", str(path)]
    _run(command)
    return path


# --- content_review measurement ---


def test_good_clip_passes(tmp_path: Path) -> None:
    clip = _clip(tmp_path / "good.mp4", video=_MOVING, audio=_NORMAL_AUDIO)
    review = content_review(clip, expect_audio=True)
    assert review.failures == ()
    assert not review.black
    assert not review.silent
    assert not review.clipping
    assert not review.slideshow


def test_black_video_is_flagged(tmp_path: Path) -> None:
    review = content_review(_clip(tmp_path / "black.mp4", video=_BLACK), expect_audio=False)
    assert review.black is True
    assert "black or broken frames" in review.failures


def test_static_video_is_a_slideshow(tmp_path: Path) -> None:
    review = content_review(_clip(tmp_path / "static.mp4", video=_STATIC), expect_audio=False)
    assert review.slideshow is True
    assert "video is effectively a slideshow" in review.failures


def test_silent_audio_is_flagged(tmp_path: Path) -> None:
    clip = _clip(tmp_path / "silent.mp4", video=_MOVING, audio=_SILENT)
    review = content_review(clip, expect_audio=True)
    assert review.silent is True
    assert "audio is silent" in review.failures


def test_clipping_audio_is_flagged(tmp_path: Path) -> None:
    clip = _clip(tmp_path / "clip.mp4", video=_MOVING, audio=_CLIPPING_AUDIO)
    review = content_review(clip, expect_audio=True)
    assert review.clipping is True
    assert "audio is clipping" in review.failures


def test_audio_checks_skipped_when_not_expected(tmp_path: Path) -> None:
    # A clip with silent audio present, but audio was not expected → audio verdicts stay False.
    clip = _clip(tmp_path / "silent2.mp4", video=_MOVING, audio=_SILENT)
    review = content_review(clip, expect_audio=False)
    assert review.silent is False
    assert review.clipping is False
    assert review.audio_mean_dbfs is None
    assert review.audio_peak_dbfs is None
    assert review.failures == ()


# --- finalize integration: content review runs on a real run, skipped on a dry run ---


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


def test_finalize_real_run_rejects_black_output(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    _clip(video_dir / "in.mp4", video=_BLACK)
    token = set_active(_ctx(video_dir, dry_run=False))
    try:
        with pytest.raises(RuntimeError):
            sfvf.finalize("in.mp4")
    finally:
        reset_active(token)


def test_finalize_real_run_accepts_good_output(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    _clip(video_dir / "in.mp4", video=_MOVING, audio=_NORMAL_AUDIO)
    token = set_active(_ctx(video_dir, dry_run=False))
    try:
        out = sfvf.finalize("in.mp4", audio="in.mp4")
    finally:
        reset_active(token)
    assert out == "final.mp4"


def test_finalize_dry_run_skips_content_review(tmp_path: Path) -> None:
    # A static (slideshow) stub would fail content review, but a dry run must skip it and succeed.
    video_dir = tmp_path / "01"
    _clip(video_dir / "in.mp4", video=_STATIC)
    token = set_active(_ctx(video_dir, dry_run=True))
    try:
        out = sfvf.finalize("in.mp4")
    finally:
        reset_active(token)
    assert out == "final.mp4"
