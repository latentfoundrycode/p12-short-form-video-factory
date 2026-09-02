"""A-1 contract: the FFmpeg/ffprobe stub-generation core.

The dry-run stub engine (arch §2.1a, SDK §10) generates placeholder assets on
demand with FFmpeg — silent audio of a given length, a colour-bars clip of a
given duration and size, a solid placeholder still — and probes media for its
real duration/resolution. These are the primitives every media stub builds on.
"""

from pathlib import Path

from sfvf import _ffmpeg

_TOL = 0.15  # seconds; FFmpeg duration lands within a frame or two of the request


def test_ffmpeg_available() -> None:
    # The gate runner and dev machines must have FFmpeg on PATH for the stub
    # engine to work; this asserts the toolchain the rest of Stage A depends on.
    assert _ffmpeg.ffmpeg_available() is True


def test_silent_audio_has_requested_duration(tmp_path: Path) -> None:
    dest = tmp_path / "narration.m4a"
    out = _ffmpeg.silent_audio(dest, duration_s=2.0)
    assert out == dest
    assert out.is_file()
    probe = _ffmpeg.probe(out)
    assert abs(probe.duration_s - 2.0) < _TOL
    assert probe.has_audio is True


def test_color_bars_has_requested_duration_and_size(tmp_path: Path) -> None:
    dest = tmp_path / "clip.mp4"
    out = _ffmpeg.color_bars(dest, duration_s=1.5, width=1080, height=1920, fps=30)
    assert out.is_file()
    probe = _ffmpeg.probe(out)
    assert abs(probe.duration_s - 1.5) < _TOL
    assert (probe.width, probe.height) == (1080, 1920)


def test_solid_image_has_requested_size(tmp_path: Path) -> None:
    dest = tmp_path / "still.png"
    out = _ffmpeg.solid_image(dest, width=640, height=360)
    assert out.is_file()
    probe = _ffmpeg.probe(out)
    assert (probe.width, probe.height) == (640, 360)


def test_probe_reports_no_audio_for_silent_video(tmp_path: Path) -> None:
    dest = tmp_path / "silent.mp4"
    out = _ffmpeg.color_bars(dest, duration_s=1.0, width=320, height=240, fps=24)
    probe = _ffmpeg.probe(out)
    assert probe.has_audio is False
