"""TASK-SSN-B3 contract: media.edit.mix -- narration + ducked music + offset SFX -> ONE track.

`media.edit.mix(narration, *, music=None, sfx=None, duck=True) -> str` mixes a narration track with
an optional music bed and optional offset SFX into a SINGLE audio track (a video-relative
path) whose duration is the longest input. When `duck=True` the music is ducked under the narration
(sidechain compression), so the music-band level where narration plays is meaningfully lower than
where narration is silent; `duck=False` leaves the music level flat. `sfx` is a list of
`(path, at_seconds)` placed at their offsets. Implemented with an ffmpeg sidechaincompress
filtergraph (KP-008 probe: ~14 dB ducking on tone fixtures; kinocut ducking primitives unverified).

Supervisor-authored frozen contract (RED-first); the builder implements sdk/sfvf/media/edit.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sfvf import media
from sfvf._ffmpeg import _binary, _run, probe
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths


def _ctx(video_dir: Path) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=False,
            paths=ContextPaths(
                video=video_dir,
                artifacts=video_dir / "artifacts",
                steps=video_dir / ".steps",
                shared=video_dir,
            ),
        )
    )


def _tone(
    dest: Path, *, freq: int, duration: float, delay_s: float = 0.0, pad_to: float | None = None
) -> None:
    filters = []
    if delay_s:
        filters.append(f"adelay={int(delay_s * 1000)}")
    if pad_to is not None:
        filters.append(f"apad=whole_dur={pad_to}")
    args = [
        _binary("ffmpeg"),
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={freq}:duration={duration}",
    ]
    if filters:
        args += ["-af", ",".join(filters)]
    args += ["-ac", "1", "-ar", "44100", str(dest)]
    _run(args)


def _band_mean_db(path: Path, *, start: float, end: float, freq: int) -> float:
    stderr = _run(
        [
            _binary("ffmpeg"),
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            f"atrim=start={start}:end={end},bandpass=f={freq}:width_type=h:width=60,volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_stderr=True,
    )
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", stderr)
    assert match, f"no mean_volume in ffmpeg output:\n{stderr}"
    return float(match.group(1))


def _audio_stream_count(path: Path) -> int:
    out = _run(
        [
            _binary("ffprobe"),
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path),
        ]
    )
    return len([line for line in out.splitlines() if line.strip()])


def _fixtures(video_dir: Path) -> None:
    video_dir.mkdir(parents=True, exist_ok=True)
    # narration: 300 Hz only in [2s,4s] of a 6s span; music: 800 Hz full 6s; sfx: 1200 Hz blip.
    _tone(video_dir / "narration.wav", freq=300, duration=2.0, delay_s=2.0, pad_to=6.0)
    _tone(video_dir / "music.wav", freq=800, duration=6.0)
    _tone(video_dir / "sfx.wav", freq=1200, duration=0.3)


def _resolve(ctx: Context, rel: str) -> Path:
    return (ctx.paths.video / rel).resolve()


def test_mix_ducks_music_under_narration(tmp_path: Path) -> None:
    _fixtures(tmp_path)
    ctx = _ctx(tmp_path)
    token = set_active(ctx)
    try:
        rel = media.edit.mix("narration.wav", music="music.wav", sfx=[("sfx.wav", 1.0)], duck=True)
    finally:
        reset_active(token)
    out = _resolve(ctx, rel)
    assert out.is_file()
    assert _audio_stream_count(out) == 1  # one track out
    assert probe(out).duration_s == pytest.approx(6.0, abs=0.2)  # longest input
    under = _band_mean_db(out, start=2.2, end=3.8, freq=800)  # music while narration plays
    clear = _band_mean_db(out, start=4.4, end=5.6, freq=800)  # music with no narration
    assert clear - under >= 6.0  # audible ducking (probe showed ~14 dB)


def test_mix_without_duck_leaves_music_flat(tmp_path: Path) -> None:
    _fixtures(tmp_path)
    ctx = _ctx(tmp_path)
    token = set_active(ctx)
    try:
        rel = media.edit.mix("narration.wav", music="music.wav", duck=False)
    finally:
        reset_active(token)
    out = _resolve(ctx, rel)
    under = _band_mean_db(out, start=2.2, end=3.8, freq=800)
    clear = _band_mean_db(out, start=4.4, end=5.6, freq=800)
    assert abs(clear - under) <= 3.0  # no ducking -> music band roughly flat across windows


def test_mix_places_offset_sfx(tmp_path: Path) -> None:
    _fixtures(tmp_path)
    ctx = _ctx(tmp_path)
    token = set_active(ctx)
    try:
        rel = media.edit.mix("narration.wav", music="music.wav", sfx=[("sfx.wav", 1.0)], duck=True)
    finally:
        reset_active(token)
    out = _resolve(ctx, rel)
    at_sfx = _band_mean_db(out, start=1.0, end=1.3, freq=1200)  # sfx placed here
    no_sfx = _band_mean_db(out, start=4.0, end=4.3, freq=1200)  # no sfx here
    assert at_sfx - no_sfx >= 6.0


def test_mix_narration_only_returns_single_track(tmp_path: Path) -> None:
    _fixtures(tmp_path)
    ctx = _ctx(tmp_path)
    token = set_active(ctx)
    try:
        rel = media.edit.mix("narration.wav")
    finally:
        reset_active(token)
    out = _resolve(ctx, rel)
    assert out.is_file()
    assert _audio_stream_count(out) == 1
    assert probe(out).duration_s == pytest.approx(6.0, abs=0.2)


def test_mix_requires_active_context() -> None:
    with pytest.raises(RuntimeError):
        media.edit.mix("narration.wav")
