from __future__ import annotations

import hashlib
from typing import TypedDict

from .._ffmpeg import silent_audio
from .._runtime import current_context

_RATE = 2.5  # words per second; dry-run duration is deterministic.


class WordTiming(TypedDict):
    word: str
    start: float
    end: float


class Speech(TypedDict):
    audio: str
    timings: list[WordTiming]
    duration: float


def speak(text: str, *, voice: str, model: str) -> Speech:
    ctx = current_context()
    if not ctx.dry_run:
        raise NotImplementedError(
            "media.speech.speak: the ElevenLabs adapter arrives in Stage B; run with dry_run=True"
        )

    words = text.split()
    duration = max(len(words), 1) / _RATE
    sha = hashlib.sha256(f"{voice}|{model}|{text}".encode()).hexdigest()[:8]
    filename = f"narration-{sha}.m4a"
    dest = ctx.paths.artifacts / filename
    ctx.paths.artifacts.mkdir(parents=True, exist_ok=True)
    silent_audio(dest, duration_s=duration)

    n = len(words)
    timings: list[WordTiming] = [
        WordTiming(word=word, start=i * duration / n, end=(i + 1) * duration / n)
        for i, word in enumerate(words)
    ]
    return Speech(
        audio=dest.relative_to(ctx.paths.video).as_posix(),
        timings=timings,
        duration=duration,
    )
