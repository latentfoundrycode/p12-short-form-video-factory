from __future__ import annotations

from typing import Any

from .._runtime import current_context
from .graphics import _artifact, _sha8


def trim(video: str, start: float, end: float) -> str:
    ctx = current_context()
    dest, rel = _artifact(ctx, f"edit-trim-{_sha8([video, start, end])}.mp4")
    abs_in = str((ctx.paths.video / video).resolve())
    _client().trim(abs_in, start=start, end=end, output=str(dest))
    return rel


def cut(clips: list[str], *, transitions: list[str] | None = None) -> str:
    ctx = current_context()
    dest, rel = _artifact(ctx, f"edit-cut-{_sha8([clips, transitions])}.mp4")
    abs_clips = [str((ctx.paths.video / clip).resolve()) for clip in clips]
    _client().merge(abs_clips, transitions=transitions, output=str(dest))
    return rel


def _client() -> Any:
    try:
        from kinocut import Client
    except ImportError as exc:  # optional `sfvf[edit]` extra
        raise RuntimeError(
            "media.edit requires the 'kinocut' package. Install the SDK 'edit' extra: "
            "pip install 'sfvf[edit]' (or pip install kinocut==1.15.1)."
        ) from exc
    return Client()
