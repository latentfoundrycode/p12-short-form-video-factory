"""Content self-review of a finished video (Architecture §5.8, SDK §6.9).

The failures a valid file can still hide — the ones a person otherwise only finds by watching the
whole video: black or broken frames, silent or clipping audio, and a result that is effectively a
slideshow when motion was intended. All are cheap, AI-free FFmpeg measurements. `finalize` runs
these on a REAL run before marking a video complete and fails the video on any failure; in a dry run
the assets are stubs (static, silent) so the content checks are skipped (structural checks remain).

Composition-DOM checks (§5.8 rows 6-8) and recording the measured results into `video.json` are
later Stage-E increments.

SKELETON — the `ContentReview`/`content_review` names and signature are frozen by
tests/sdk/test_content_review.py; the builder fills the body.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# House-format defaults. Thresholds calibrated to the declared `[output]` format are deferred until
# `[output]` reaches the runtime Context (like the fixed house format); these are the vertical-short
# defaults. Audio in dBFS (0 = full scale); motion is a mean inter-frame scene score in [0,1].
SILENCE_MEAN_DBFS = -60.0  # mean level at or below this reads as silent
CLIPPING_PEAK_DBFS = -0.1  # peak level at or above this reads as clipping
SLIDESHOW_MOTION_MIN = 0.006  # mean inter-frame change below this reads as a slideshow


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
    raise NotImplementedError
