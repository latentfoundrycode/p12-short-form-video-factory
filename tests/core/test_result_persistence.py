"""A-2 contract (supervisor side): a returned Result is persisted whole to video.json.

The runner emits every Result field as the `result` event; the supervisor must retain all
of them in the video record — not just video/caption — because SDK §3.3 records `extra`
verbatim and displays `notes`, and sequence continuity (`ctx.previous`) reads a prior
video's `Result.extra`. Drives the real supervisor against the `returns_result` stub.
"""

import sys
from pathlib import Path

from app.core.env import EnvBlocked, EnvReady
from app.core.records import read_video
from app.core.supervisor import RunBusy, run_request

STUBS = Path(__file__).resolve().parent.parent / "stubs"


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def test_returned_result_fields_persisted_to_video_json(tmp_path: Path) -> None:
    result = run_request(
        STUBS / "returns_result",
        params={"topic": "t"},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,
    )
    assert not isinstance(result, EnvBlocked | RunBusy)

    run_dir = next((tmp_path / "runs" / "returns_result").iterdir())
    video = read_video(run_dir / "01")
    assert video.status == "complete"
    # The whole Result reaches video.json, not just video/caption.
    assert video.result == {
        "video": "artifacts/final.mp4",
        "caption": "hi",
        "hashtags": ["a", "b"],
        "cover_frame_s": 1.0,
        "notes": "n",
        "extra": {"k": 1},
    }
