"""Speech-1 contract: `sfvf.media.speech` — local narration (Chatterbox TTS + WhisperX alignment).

`speak(text, *, voice, model)` returns a `Speech` — a JSON-native TypedDict (`audio` a
video-relative path string, `timings` a list of word-timing dicts, `duration` the real audio length)
so the result caches through `ctx.step` (SDK §5.5). In dry-run it writes silent audio of a plausible
length via the FFmpeg core (A-1). In REAL mode it synthesizes speech locally and force-aligns the
known text to the audio for word timings — no key, no network, no paid provider.

The real path uses two heavy, GPU-backed libraries (Chatterbox, WhisperX) behind two module-level
SEAMS — `speech._synthesize(...)` and `speech._align(...)` — lazy-imported only when called. These
tests patch the seams so CI never imports torch; the ffmpeg m4a encode and `probe` duration stay
REAL. The real libraries are proven by the local spike, not in CI.
"""

import json
import subprocess
from pathlib import Path

import pytest
from sfvf import media
from sfvf._ffmpeg import probe
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths
from sfvf.media.speech import WordTiming


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


def _write_wav(dest: Path, *, seconds: float) -> None:
    # A real, probeable PCM wav so the (real) ffmpeg m4a encode + probe in speak() work in CI.
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=mono:sample_rate=24000",
            "-t",
            str(seconds),
            "-c:a",
            "pcm_s16le",
            str(dest),
        ],
        check=True,
        capture_output=True,
    )


def test_speak_requires_an_active_context() -> None:
    with pytest.raises(RuntimeError):
        media.speech.speak("hi", voice="v", model="m")


def test_speak_dry_run_returns_json_native_speech(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    token = set_active(_ctx(video_dir, dry_run=True))
    try:
        speech = media.speech.speak("one two three four", voice="narrator", model="local")
    finally:
        reset_active(token)

    assert isinstance(speech, dict)
    json.dumps(speech)  # JSON-native (SDK §5.5) — must not raise
    assert isinstance(speech["audio"], str)
    assert not Path(speech["audio"]).is_absolute()
    assert (video_dir / speech["audio"]).is_file()
    assert isinstance(speech["duration"], float)
    assert speech["duration"] > 0
    assert [t["word"] for t in speech["timings"]] == ["one", "two", "three", "four"]


def test_speak_dry_run_is_deterministic(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    token = set_active(_ctx(a, dry_run=True))
    try:
        first = media.speech.speak("hello world", voice="v", model="m")
    finally:
        reset_active(token)
    token = set_active(_ctx(b, dry_run=True))
    try:
        second = media.speech.speak("hello world", voice="v", model="m")
    finally:
        reset_active(token)
    assert first == second


# --- real mode: assembled from the (mocked) synth + align seams ---

_CANNED: list[WordTiming] = [
    {"word": "hello", "start": 0.10, "end": 0.42},
    {"word": "there", "start": 0.50, "end": 0.90},
]


def test_speak_real_mode_assembles_speech_from_seams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()

    def fake_synthesize(text: str, *, voice: str, model: str, dest: Path) -> None:
        _write_wav(dest, seconds=1.0)

    monkeypatch.setattr(media.speech, "_synthesize", fake_synthesize)
    monkeypatch.setattr(media.speech, "_align", lambda text, audio: list(_CANNED))

    token = set_active(_ctx(video_dir, dry_run=False))
    try:
        speech = media.speech.speak("hello there", voice="narrator", model="local")
    finally:
        reset_active(token)

    json.dumps(speech)  # JSON-native
    # audio: a video-relative .m4a that really exists and probes as audio
    assert isinstance(speech["audio"], str)
    assert not Path(speech["audio"]).is_absolute()
    assert speech["audio"].endswith(".m4a")
    audio_abs = video_dir / speech["audio"]
    assert audio_abs.is_file()
    assert probe(audio_abs).has_audio is True
    # duration is the real measured length of the produced audio (~1.0s here)
    assert isinstance(speech["duration"], float)
    assert speech["duration"] == pytest.approx(1.0, abs=0.2)
    # timings come from the alignment seam, unchanged
    assert speech["timings"] == _CANNED


def test_speak_real_mode_passes_text_voice_model_to_seams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    synth_calls: list[dict[str, object]] = []
    align_calls: list[tuple[str, str]] = []

    def fake_synthesize(text: str, *, voice: str, model: str, dest: Path) -> None:
        synth_calls.append({"text": text, "voice": voice, "model": model})
        _write_wav(dest, seconds=0.5)

    def fake_align(text: str, audio: Path) -> list[WordTiming]:
        align_calls.append((text, Path(audio).name))
        return list(_CANNED)

    monkeypatch.setattr(media.speech, "_synthesize", fake_synthesize)
    monkeypatch.setattr(media.speech, "_align", fake_align)

    token = set_active(_ctx(video_dir, dry_run=False))
    try:
        media.speech.speak("the script text", voice="narrator", model="local-tts")
    finally:
        reset_active(token)

    assert synth_calls == [{"text": "the script text", "voice": "narrator", "model": "local-tts"}]
    # alignment runs on the delivered .m4a, so timings and the probed duration describe one file
    assert len(align_calls) == 1
    assert align_calls[0][0] == "the script text"
    assert align_calls[0][1].endswith(".m4a")


def test_speak_real_mode_fails_closed_on_empty_timings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Non-empty text but the aligner returns no timings → a Speech with audio and empty captions
    # would be a silent caption miss. speak() must fail closed instead.
    video_dir = tmp_path / "01"
    video_dir.mkdir()

    def fake_synthesize(text: str, *, voice: str, model: str, dest: Path) -> None:
        _write_wav(dest, seconds=0.5)

    monkeypatch.setattr(media.speech, "_synthesize", fake_synthesize)
    monkeypatch.setattr(media.speech, "_align", lambda text, audio: [])

    token = set_active(_ctx(video_dir, dry_run=False))
    try:
        with pytest.raises(RuntimeError):
            media.speech.speak("some spoken words here", voice="v", model="m")
    finally:
        reset_active(token)
