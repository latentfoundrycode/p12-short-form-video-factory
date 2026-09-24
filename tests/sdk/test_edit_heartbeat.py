"""`sfvf.media.edit` heartbeat wrapping (H6).

`trim`/`cut` drive FFmpeg synchronously through kinocut, so a long concat/encode produces no
workflow stdout and the 300 s silence watchdog could kill it. Both must run inside
`heartbeat_during(...)` so periodic heartbeats keep the watchdog fed. These unit tests stub the
kinocut client and the heartbeat helper, so they need neither kinocut nor FFmpeg.
"""

from __future__ import annotations

from pathlib import Path

from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths
from sfvf.media import edit


def _ctx(video_dir: Path) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=True,
            paths=ContextPaths(
                video=video_dir,
                artifacts=video_dir / "artifacts",
                steps=video_dir / ".steps",
                shared=video_dir,
            ),
        )
    )


class _RecordingHeartbeat:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, name: str, *, waiting_on: str, **_kw: object) -> _RecordingHeartbeat:
        self.calls.append((name, waiting_on))
        return self

    def __enter__(self) -> _RecordingHeartbeat:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


class _FakeClient:
    def trim(self, *_a: object, **_k: object) -> None:
        return None

    def merge(self, *_a: object, **_k: object) -> None:
        return None


def test_trim_wraps_the_ffmpeg_op_in_a_heartbeat(tmp_path: Path, monkeypatch) -> None:
    recorder = _RecordingHeartbeat()
    monkeypatch.setattr(edit, "heartbeat_during", recorder)
    monkeypatch.setattr(edit, "_client", lambda: _FakeClient())
    (tmp_path / "in.mp4").write_bytes(b"x")
    token = set_active(_ctx(tmp_path))
    try:
        edit.trim("in.mp4", 0.0, 1.0)
    finally:
        reset_active(token)
    assert ("edit", "ffmpeg") in recorder.calls


def test_cut_wraps_the_ffmpeg_op_in_a_heartbeat(tmp_path: Path, monkeypatch) -> None:
    recorder = _RecordingHeartbeat()
    monkeypatch.setattr(edit, "heartbeat_during", recorder)
    monkeypatch.setattr(edit, "_client", lambda: _FakeClient())
    token = set_active(_ctx(tmp_path))
    try:
        edit.cut(["a.mp4", "b.mp4"])
    finally:
        reset_active(token)
    assert ("edit", "ffmpeg") in recorder.calls
