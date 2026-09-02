"""A-6 contract: `sfvf.finalize` — the mandatory last step (SDK §6.9, arch §5.8).

`finalize(video, audio=None, captions=None)` applies the house format with FFmpeg
(codec/fps/resolution/loudness) and returns the finished file's video-relative path.
It is REAL in both modes (FFmpeg is local/free). Its self-review here is STRUCTURAL —
the output is a valid file of the house resolution with the expected streams; the §5.8
content checks (silence, black frames, slideshow) need real assets and land in Stage E.
It is reachable as both `sfvf.finalize` and `media.finalize`.
"""

from pathlib import Path

import pytest
import sfvf
from sfvf import media
from sfvf._ffmpeg import probe
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths

_W = 1080
_H = 1920


def _ctx(video_dir: Path) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=True,
            paths=ContextPaths(
                video=video_dir,
                artifacts=video_dir / "artifacts",
                steps=video_dir / ".steps",
                shared=video_dir,
            ),
        )
    )


def test_finalize_is_exposed_both_ways() -> None:
    assert sfvf.finalize is media.finalize


def test_finalize_requires_active_context() -> None:
    with pytest.raises(RuntimeError):
        sfvf.finalize("artifacts/x.mp4")


def test_finalize_full_produces_house_format_with_streams(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    token = set_active(_ctx(video_dir))
    try:
        clip = media.graphics.render("<h1>hi</h1>", duration_s=2.0)
        speech = media.speech.speak("one two three", voice="v", model="m")
        caps = media.graphics.captions(speech["audio"], speech["timings"], "bold")
        out = sfvf.finalize(clip, audio=speech["audio"], captions=caps)
    finally:
        reset_active(token)

    assert isinstance(out, str)
    assert not Path(out).is_absolute()
    final = video_dir / out
    assert final.is_file()
    probed = probe(final)
    assert (probed.width, probed.height) == (_W, _H)
    assert probed.duration_s > 0
    assert probed.has_audio is True


def test_finalize_video_only(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    token = set_active(_ctx(video_dir))
    try:
        clip = media.graphics.render("<h1>solo</h1>", duration_s=1.5)
        out = sfvf.finalize(clip)
    finally:
        reset_active(token)
    final = video_dir / out
    probed = probe(final)
    assert (probed.width, probed.height) == (_W, _H)
    assert probed.duration_s > 0


def test_finalize_rejects_missing_input(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    token = set_active(_ctx(video_dir))
    try:
        with pytest.raises((RuntimeError, FileNotFoundError, ValueError)):
            sfvf.finalize("artifacts/does-not-exist.mp4")
    finally:
        reset_active(token)


def test_finalize_rejects_escaping_input(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    token = set_active(_ctx(video_dir))
    try:
        with pytest.raises((ValueError, RuntimeError)):
            sfvf.finalize("../outside.mp4")
    finally:
        reset_active(token)
