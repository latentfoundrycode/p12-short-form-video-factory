"""Content self-review of a finished video (Architecture §5.8, SDK §6.9).

The failures a valid file can still hide — the ones a person otherwise only finds by watching the
whole video: black or broken frames, silent or clipping audio, and a result that is effectively a
slideshow when motion was intended. All are cheap, AI-free FFmpeg measurements. `finalize` runs
these on a REAL run before marking a video complete and fails the video on any failure; in a dry run
the assets are stubs (static, silent) so the content checks are skipped (structural checks remain).

Composition-DOM checks (§5.8 rows 6-8) and recording the measured results into `video.json` are
later Stage-E increments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ._ffmpeg import _binary, _run, probe

# House-format defaults. Thresholds calibrated to the declared `[output]` format are deferred until
# `[output]` reaches the runtime Context (like the fixed house format); these are the vertical-short
# defaults. Audio in dBFS (0 = full scale); motion is a mean inter-frame scene score in [0,1].
SILENCE_MEAN_DBFS = -60.0  # mean level at or below this reads as silent
CLIPPING_PEAK_DBFS = -0.1  # peak level at or above this reads as clipping
SLIDESHOW_MOTION_MIN = 0.006  # mean inter-frame change below this reads as a slideshow
# blackdetect `d` is a minimum interval; a share of the clip at or above this is non-trivial.
_BLACK_FRACTION = 0.05
_BLACKDETECT = "blackdetect=d=0.05"

_BLACK_DURATION = re.compile(r"black_duration:\s*([0-9.]+)")
_MEAN_VOLUME = re.compile(r"mean_volume:\s*(\S+)\s*dB")
_MAX_VOLUME = re.compile(r"max_volume:\s*(\S+)\s*dB")
_SCENE_SCORE = re.compile(r"lavfi\.scd\.score=([0-9.eE+-]+)")


@dataclass(frozen=True)
class ContentReview:
    """The measured content self-review of a finished video (§5.8).

    Booleans are the verdicts; the measurements are kept so a borderline case is inspectable (and so
    a later increment can record them into `video.json`). `audio_*` are None when audio was not
    expected/measured. `failures` names each failed check (empty means the video passed).
    """

    black: bool
    silent: bool
    clipping: bool
    slideshow: bool
    audio_mean_dbfs: float | None
    audio_peak_dbfs: float | None
    motion_score: float

    @property
    def failures(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.black:
            reasons.append("black or broken frames")
        if self.silent:
            reasons.append("audio is silent")
        if self.clipping:
            reasons.append("audio is clipping")
        if self.slideshow:
            reasons.append("video is effectively a slideshow")
        return tuple(reasons)


def content_review(path: Path, *, expect_audio: bool) -> ContentReview:
    """Measure the finished video's content checks (§5.8) with FFmpeg.

    Detects black/broken frames and a slideshow (too little inter-frame change) from the video; when
    `expect_audio`, measures mean/peak levels and flags silent or clipping audio. Audio verdicts are
    False and the levels None when `expect_audio` is False. Pure and read-only; does not raise on a
    normal file — the caller decides what a failure means.
    """
    duration_s = probe(path).duration_s
    black = _black_frames(path, duration_s)
    motion_score = _motion_score(path)
    if expect_audio:
        mean_dbfs, peak_dbfs = _volume(path)
        silent = mean_dbfs <= SILENCE_MEAN_DBFS
        clipping = peak_dbfs >= CLIPPING_PEAK_DBFS
    else:
        mean_dbfs = None
        peak_dbfs = None
        silent = False
        clipping = False
    return ContentReview(
        black=black,
        silent=silent,
        clipping=clipping,
        slideshow=motion_score < SLIDESHOW_MOTION_MIN,
        audio_mean_dbfs=mean_dbfs,
        audio_peak_dbfs=peak_dbfs,
        motion_score=motion_score,
    )


def _black_frames(path: Path, duration_s: float) -> bool:
    log = _filter_log(path, "-vf", _BLACKDETECT, "-an")
    black_s = sum(float(match) for match in _BLACK_DURATION.findall(log))
    if duration_s <= 0:
        return black_s > 0
    return (black_s / duration_s) >= _BLACK_FRACTION


def _motion_score(path: Path) -> float:
    # `select='gte(scene,0)'` prints lavfi.scene_score, but its mean for gradual test
    # patterns (and letterboxed house-format output) sits below SLIDESHOW_MOTION_MIN.
    # scdet's scene score is the equivalent inter-frame measure in [0, 1].
    log = _filter_log(path, "-vf", "scdet,metadata=print", "-an")
    scores = [float(match) for match in _SCENE_SCORE.findall(log)]
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def _volume(path: Path) -> tuple[float, float]:
    log = _filter_log(path, "-af", "volumedetect", "-vn")
    return _parse_db(log, _MEAN_VOLUME), _parse_db(log, _MAX_VOLUME)


def _parse_db(log: str, pattern: re.Pattern[str]) -> float:
    match = pattern.search(log)
    if match is None:
        return float("-inf")
    try:
        return float(match.group(1))
    except ValueError:
        return float("-inf")


def _filter_log(path: Path, *args: str) -> str:
    return _run(
        [
            _binary("ffmpeg"),
            "-hide_banner",
            "-nostdin",
            "-i",
            str(path),
            *args,
            "-f",
            "null",
            "-",
        ],
        capture_stderr=True,
    )
