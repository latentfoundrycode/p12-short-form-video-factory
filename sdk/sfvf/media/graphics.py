from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TypedDict

from .._ffmpeg import color_bars
from .._runtime import current_context
from ..context import Context
from .speech import WordTiming

_WIDTH = 1080
_HEIGHT = 1920
_FPS = 30

_SAFE_ZONE_CSS = """\
.safe-zone {
  padding-top: 12.5%;
  padding-right: 5%;
  padding-bottom: 18%;
  padding-left: 5%;
}
"""


class Violation(TypedDict):
    kind: str
    detail: str


def render(composition_html: str, *, duration_s: float) -> str:
    ctx = current_context()
    if not ctx.dry_run:
        raise NotImplementedError(
            "media.graphics.render: the HyperFrames adapter arrives in Stage B; "
            "run with dry_run=True"
        )
    sha = _sha8(f"{composition_html}{duration_s}")
    dest, rel = _artifact(ctx, f"render-{sha}.mp4")
    color_bars(dest, duration_s=duration_s, width=_WIDTH, height=_HEIGHT, fps=_FPS)
    return rel


def captions(audio: str, timings: list[WordTiming], style: str) -> str:
    ctx = current_context()
    if not ctx.dry_run:
        raise NotImplementedError(
            "media.graphics.captions: the HyperFrames adapter arrives in Stage B; "
            "run with dry_run=True"
        )
    sha = _sha8(f"{audio}{json.dumps(timings, sort_keys=True)}{style}")
    dest, rel = _artifact(ctx, f"captions-{sha}.srt")
    dest.write_text(_srt_from_timings(timings), encoding="utf-8")
    return rel


def safe_zone_css() -> str:
    ctx = current_context()
    sha = _sha8(_SAFE_ZONE_CSS)
    dest, rel = _artifact(ctx, f"safe-zone-{sha}.css")
    dest.write_text(_SAFE_ZONE_CSS, encoding="utf-8")
    return rel


def check(composition_html: str, *, safe_zone: bool = True) -> list[Violation]:
    ctx = current_context()
    if not ctx.dry_run:
        raise NotImplementedError(
            "media.graphics.check: the HyperFrames adapter arrives in Stage B; "
            "run with dry_run=True"
        )
    _ = composition_html, safe_zone
    return []


def _sha8(material: str) -> str:
    return hashlib.sha256(material.encode()).hexdigest()[:8]


def _artifact(ctx: Context, filename: str) -> tuple[Path, str]:
    ctx.paths.artifacts.mkdir(parents=True, exist_ok=True)
    dest = ctx.paths.artifacts / filename
    return dest, dest.relative_to(ctx.paths.video).as_posix()


def _srt_from_timings(timings: list[WordTiming]) -> str:
    blocks: list[str] = []
    for index, cue in enumerate(timings, start=1):
        blocks.append(
            f"{index}\n{_srt_timestamp(cue['start'])} --> {_srt_timestamp(cue['end'])}\n"
            f"{cue['word']}\n"
        )
    return "\n".join(blocks)


def _srt_timestamp(seconds: float) -> str:
    total_ms = max(round(seconds * 1000), 0)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
