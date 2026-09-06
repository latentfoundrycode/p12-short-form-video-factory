from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any, TypedDict

from .._ffmpeg import encode_m4a, probe, silent_audio
from .._runtime import current_context

_RATE = 2.5  # words per second; dry-run duration is deterministic.

_tts_lock = threading.Lock()
_tts_model: Any | None = None

_align_lock = threading.Lock()
_align_bundle: tuple[Any, Any, str] | None = None


class WordTiming(TypedDict):
    word: str
    start: float
    end: float


class Speech(TypedDict):
    audio: str
    timings: list[WordTiming]
    duration: float


def _synthesize(text: str, *, voice: str, model: str, dest: Path) -> None:
    """Synthesize `text` to a wav file at `dest` on the GPU (Chatterbox).

    SEAM — lazy-imports Chatterbox so CI (which patches this) never loads torch. Builder implements.
    """
    try:
        import torch
        import torchaudio
        from chatterbox.tts import ChatterboxTTS
    except ImportError as exc:
        raise RuntimeError(
            "media.speech.speak requires the Chatterbox TTS packages. Install the SDK "
            "'speech' extra: pip install 'sfvf[speech]'."
        ) from exc

    # First cut: default Chatterbox voice/model. `voice`/`model` accepted for later mapping.
    del voice, model

    global _tts_model
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _tts_lock:
        if _tts_model is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            _tts_model = ChatterboxTTS.from_pretrained(device=device)
        # generate mutates instance state; hold the lock so ctx.map concurrency cannot race.
        wav = _tts_model.generate(text).detach().cpu()
        sample_rate = _tts_model.sr
    torchaudio.save(str(dest), wav, sample_rate)


def _align(text: str, audio: Path) -> list[WordTiming]:
    """Force-align the known `text` to `audio`, returning word timings (WhisperX).

    SEAM — lazy-imports WhisperX so CI (which patches this) never loads torch. Builder implements.
    """
    try:
        import torch
        import whisperx
    except ImportError as exc:
        raise RuntimeError(
            "media.speech.speak requires the 'whisperx' package. Install the SDK "
            "'speech' extra: pip install 'sfvf[speech]'."
        ) from exc

    global _align_bundle
    a = whisperx.load_audio(str(audio))
    total = len(a) / 16000.0
    segments = [{"text": text, "start": 0.0, "end": total}]
    with _align_lock:
        if _align_bundle is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model_a, metadata = whisperx.load_align_model(language_code="en", device=device)
            _align_bundle = (model_a, metadata, device)
        model_a, metadata, device = _align_bundle
        # align mutates the cached model; hold the lock across the call, not just the load.
        result = whisperx.align(
            segments, model_a, metadata, a, device, return_char_alignments=False
        )

    timings: list[WordTiming] = []
    for entry in result.get("word_segments") or []:
        if not isinstance(entry, dict):
            continue
        start = entry.get("start")
        end = entry.get("end")
        if isinstance(start, bool) or isinstance(end, bool):
            continue
        if not isinstance(start, int | float) or not isinstance(end, int | float):
            continue
        word = entry.get("word")
        timings.append(
            WordTiming(
                word=word if isinstance(word, str) else str(word or ""),
                start=float(start),
                end=float(end),
            )
        )
    return timings


def speak(text: str, *, voice: str, model: str) -> Speech:
    ctx = current_context()
    if ctx.dry_run:
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

    ctx.paths.artifacts.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(f"{voice}|{model}|{text}".encode()).hexdigest()[:8]
    wav = ctx.paths.artifacts / f"narration-{sha}.wav"
    dest = ctx.paths.artifacts / f"narration-{sha}.m4a"
    _synthesize(text, voice=voice, model=model, dest=wav)
    encode_m4a(wav, dest)
    timings = _align(text, dest)
    if text.split() and not timings:
        raise RuntimeError(
            "media.speech.speak: alignment produced no word timings for non-empty text"
        )
    duration = probe(dest).duration_s
    return Speech(
        audio=dest.relative_to(ctx.paths.video).as_posix(),
        timings=timings,
        duration=duration,
    )
