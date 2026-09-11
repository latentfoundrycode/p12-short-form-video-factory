"""E-3 contract: the supervisor records the self-review into video.json (Architecture §5.8).

§5.8: "All results are written into `video.json`, so a borderline case can be inspected afterwards."
`finalize` emits a `self_review` event carrying every check's result (structural, content, and
composition); the supervisor captures it — as it captures the `result` and `cost` events — and
writes it to `video.json` as `VideoRecord.self_review` (the event minus its `t` tag). A run that
emits no `self_review` records no block. As a write path it is secret-redacted, like `cost`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.core.env import EnvBlocked, EnvReady
from app.core.records import read_video
from app.core.supervisor import RunBusy, run_request

STUBS = Path(__file__).resolve().parent.parent / "stubs"


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def _run(workflow: Path, tmp_path: Path, **kwargs: object) -> Path:
    result = run_request(
        workflow,
        params={},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,
        **kwargs,
    )
    assert not isinstance(result, EnvBlocked | RunBusy)
    workflow_dir = next((tmp_path / "runs").iterdir())
    return next(workflow_dir.iterdir())


def test_self_review_event_is_recorded_into_video_json(tmp_path: Path) -> None:
    run_dir = _run(STUBS / "emits_self_review", tmp_path)
    video = read_video(run_dir / "01")
    assert video.status == "complete"
    assert video.self_review is not None
    sr = video.self_review
    # The recorded block is the emitted event minus its "t" tag.
    assert "t" not in sr
    assert sr["passed"] is True
    assert sr["structural"]["width"] == 1080
    assert sr["structural"]["height"] == 1920
    assert sr["content"]["black"] is False
    assert sr["content"]["motion_score"] == 0.05
    assert sr["composition"] == {"checked": 1, "violations": []}
    assert sr["failures"] == []


def test_no_self_review_event_records_no_block(tmp_path: Path) -> None:
    run_dir = _run(STUBS / "succeeds", tmp_path)
    video = read_video(run_dir / "01")
    assert video.status == "complete"
    assert video.self_review is None


def test_self_review_block_redacts_injected_secret(tmp_path: Path) -> None:
    # The self_review block is a write path, so an injected secret that surfaces in it (here in a
    # composition violation detail) must be redacted — matching events.jsonl, result, and cost (§8).
    run_dir = _run(
        STUBS / "leaks_self_review_secret",
        tmp_path,
        secrets={"OPENROUTER_API_KEY": "sk-secret-xyz"},
    )
    video = read_video(run_dir / "01")
    assert video.status == "complete"
    assert video.self_review is not None
    dumped = json.dumps(video.self_review)
    assert "sk-secret-xyz" not in dumped
    assert "[REDACTED]" in dumped
