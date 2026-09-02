"""A-4 contract: `sfvf.media.speech` narration stub (SDK §6.4).

`speak(text, *, voice, model)` returns a `Speech` — a JSON-native TypedDict
(`audio` a video-relative path string, `timings` a list of word-timing dicts,
`duration` the real audio length) so the result caches through `ctx.step` (SDK §5.5).
In dry-run it writes silent audio of a plausible length via the FFmpeg core (A-1); the
real ElevenLabs adapter is Stage B, so the non-dry path raises.
"""

import json
from pathlib import Path

import pytest
from sfvf import media
from sfvf._ffmpeg import probe
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths


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


def test_speak_requires_an_active_context() -> None:
    with pytest.raises(RuntimeError):
        media.speech.speak("hi", voice="v", model="m")


def test_speak_dry_run_returns_json_native_speech(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    token = set_active(_ctx(video_dir, dry_run=True))
    try:
        speech = media.speech.speak("one two three four", voice="narrator", model="eleven-x")
    finally:
        reset_active(token)

    assert isinstance(speech, dict)
    json.dumps(speech)  # JSON-native (SDK §5.5) — must not raise

    # audio is a video-relative path to a real audio file whose length matches duration.
    assert isinstance(speech["audio"], str)
    assert not Path(speech["audio"]).is_absolute()
    audio_abs = video_dir / speech["audio"]
    assert audio_abs.is_file()
    assert isinstance(speech["duration"], float)
    assert speech["duration"] > 0
    probed = probe(audio_abs)
    assert probed.has_audio is True
    assert abs(probed.duration_s - speech["duration"]) < 0.2

    # timings cover the words in order, monotonic, within [0, duration].
    assert [t["word"] for t in speech["timings"]] == ["one", "two", "three", "four"]
    prev_end = 0.0
    for t in speech["timings"]:
        assert 0.0 <= t["start"] <= t["end"] <= speech["duration"] + 0.01
        assert t["start"] >= prev_end - 0.001
        prev_end = t["end"]


def test_speak_dry_run_is_deterministic(tmp_path: Path) -> None:
    first_dir = tmp_path / "a"
    first_dir.mkdir()
    second_dir = tmp_path / "b"
    second_dir.mkdir()

    token = set_active(_ctx(first_dir, dry_run=True))
    try:
        first = media.speech.speak("hello world", voice="v", model="m")
    finally:
        reset_active(token)
    token = set_active(_ctx(second_dir, dry_run=True))
    try:
        second = media.speech.speak("hello world", voice="v", model="m")
    finally:
        reset_active(token)

    # Same inputs → identical Speech (same relative audio path, duration, timings).
    assert first == second


def test_speak_non_dry_run_raises_not_implemented(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    token = set_active(_ctx(video_dir, dry_run=False))
    try:
        with pytest.raises(NotImplementedError):
            media.speech.speak("hi", voice="v", model="m")
    finally:
        reset_active(token)
