"""E-3 contract: `finalize` emits a `self_review` event carrying every §5.8 check result.

Per §5.8 "All results are written into `video.json`": `finalize` gathers the structural checks, the
E-1 content review, and the E-2 composition review into one `{"t":"self_review", ...}` event and
emits it — and it emits it BEFORE raising on a hard failure, so a failed video's review is recorded
for inspection too. `passed` is true iff `failures` is empty; `content` is null in a dry run (the
content review is skipped, as in E-1). FFmpeg lavfi fixtures, no real spend; the composition part is
toolchain-gated (it drives the real headless renderer/check).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sfvf
from sfvf._ffmpeg import _binary, _run
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths

_MOVING = "testsrc2=size=320x240:rate=30"
_BLACK = "color=c=black:s=320x240:r=30"
_NORMAL_AUDIO = "sine=frequency=440:sample_rate=44100,volume=0.3"


def _clip(path: Path, *, video: str, audio: str | None = None, dur: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [_binary("ffmpeg"), "-y", "-fflags", "+bitexact", "-f", "lavfi", "-i", video]
    if audio is not None:
        command += ["-f", "lavfi", "-i", audio, "-c:a", "aac", "-shortest"]
    command += ["-t", str(dur), "-pix_fmt", "yuv420p", str(path)]
    _run(command)
    return path


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


def _self_review_event(capsys: pytest.CaptureFixture[str]) -> dict:
    events = []
    for line in capsys.readouterr().out.splitlines():
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                events.append(json.loads(stripped))
            except ValueError:
                continue
    reviews = [e for e in events if e.get("t") == "self_review"]
    assert len(reviews) == 1, f"expected exactly one self_review event, got {len(reviews)}"
    return reviews[0]


def test_finalize_emits_self_review_on_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    video_dir = tmp_path / "01"
    _clip(video_dir / "in.mp4", video=_MOVING, audio=_NORMAL_AUDIO)
    token = set_active(_ctx(video_dir, dry_run=False))
    try:
        sfvf.finalize("in.mp4", audio="in.mp4")
    finally:
        reset_active(token)
    sr = _self_review_event(capsys)
    assert sr["passed"] is True
    assert sr["failures"] == []
    assert sr["structural"]["width"] == 1080
    assert sr["structural"]["height"] == 1920
    assert sr["structural"]["has_audio"] is True
    assert sr["structural"]["has_captions"] is False
    # content present on a real run, with the E-1 measurements.
    assert sr["content"]["black"] is False
    assert sr["content"]["silent"] is False
    assert sr["content"]["clipping"] is False
    assert isinstance(sr["content"]["motion_score"], int | float)
    assert isinstance(sr["content"]["audio_mean_dbfs"], int | float)
    # no composition render among the inputs → nothing checked.
    assert sr["composition"] == {"checked": 0, "violations": []}


def test_finalize_emits_self_review_before_raising_on_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    video_dir = tmp_path / "01"
    _clip(video_dir / "in.mp4", video=_BLACK)
    token = set_active(_ctx(video_dir, dry_run=False))
    try:
        with pytest.raises(RuntimeError):
            sfvf.finalize("in.mp4")
    finally:
        reset_active(token)
    # The self_review must have been emitted BEFORE the raise, recording the failure.
    sr = _self_review_event(capsys)
    assert sr["passed"] is False
    assert sr["content"]["black"] is True
    assert any("black" in f for f in sr["failures"])


def test_finalize_self_review_content_is_null_in_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    video_dir = tmp_path / "01"
    _clip(video_dir / "in.mp4", video=_MOVING)
    token = set_active(_ctx(video_dir, dry_run=True))
    try:
        sfvf.finalize("in.mp4")
    finally:
        reset_active(token)
    sr = _self_review_event(capsys)
    # A dry run skips the content review (stub media is static/silent), so content is null; the
    # event is still emitted with the structural (and any composition) results.
    assert sr["content"] is None
    assert sr["passed"] is True
    assert sr["structural"]["width"] == 1080
