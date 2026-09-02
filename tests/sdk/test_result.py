"""A-2 contract: the `Result` a workflow returns, and how the runner records it.

A workflow's `run()` returns `Result(video=..., caption=..., ...)` (SDK §3.3). The
runner turns that into the `result` event the supervisor already captures, with the
video path made relative to the video folder (SDK §5.5). This is what lets an example
workflow's finished file reach `video.json`.
"""

import json
from pathlib import Path

import pytest
from sfvf import Result
from sfvf.context import ContextFile, ContextPaths
from sfvf.runner import _run

STUBS = Path(__file__).resolve().parent.parent / "stubs"


def _context_file(video_dir: Path) -> ContextFile:
    return ContextFile(
        settings={"topic": "t"},
        paths=ContextPaths(
            video=video_dir,
            artifacts=video_dir / "artifacts",
            steps=video_dir / ".steps",
            shared=video_dir,
        ),
    )


def test_result_defaults() -> None:
    r = Result(video=Path("artifacts/final.mp4"))
    assert r.video == Path("artifacts/final.mp4")
    assert r.caption is None
    assert r.hashtags is None
    assert r.cover_frame_s == 1.0
    assert r.notes is None
    assert r.extra is None


def test_result_carries_all_fields() -> None:
    r = Result(
        video=Path("v.mp4"),
        caption="c",
        hashtags=["x"],
        cover_frame_s=2.5,
        notes="n",
        extra={"k": 1},
    )
    assert r.caption == "c"
    assert r.hashtags == ["x"]
    assert r.cover_frame_s == 2.5
    assert r.notes == "n"
    assert r.extra == {"k": 1}


def test_runner_emits_result_event_from_returned_result(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    context_path = video_dir / "context.json"
    context_path.write_text(
        json.dumps(_context_file(video_dir).model_dump(mode="json")),
        encoding="utf-8",
    )

    # The video entrypoint runs without a --result file; the finished video is
    # conveyed through the emitted `result` event, not a result.json.
    _run(STUBS / "returns_result", context_path, entry="entrypoint", result_path=None)

    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.out.splitlines() if line.strip()]
    result_events = [e for e in events if e.get("t") == "result"]
    assert len(result_events) == 1
    event = result_events[0]
    # Video path is relative to the video folder, POSIX-style (SDK §5.5).
    assert event["video"] == "artifacts/final.mp4"
    assert event["caption"] == "hi"
    assert event["hashtags"] == ["a", "b"]
    assert event["notes"] == "n"
    assert event["extra"] == {"k": 1}
    assert event["cover_frame_s"] == 1.0
