"""C-1 contract: the supervisor records per-video cost from `cost` events into video.json.

`video.json` carries `cost: {"actual": {meter: amount}, "uncached": {meter: amount}}` (Architecture
§4.2). `actual` is what was really spent this run; `uncached` is the same work with nothing reused
(the basis for future estimates). The supervisor aggregates the child's `cost` events: each adds its
amount to `uncached[meter]`, and also to `actual[meter]` when it was NOT a cache hit. A meter shows
in `actual` only if it had a non-cached cost, and in `uncached` if it had any cost. A run that emits
no cost events records no `cost` block. No network, no spend.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.core.env import EnvBlocked, EnvReady
from app.core.records import read_video
from app.core.supervisor import RunBusy, run_request

STUBS = Path(__file__).resolve().parent.parent / "stubs"


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def _run(workflow: Path, tmp_path: Path) -> Path:
    result = run_request(
        workflow,
        params={},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,
    )
    assert not isinstance(result, EnvBlocked | RunBusy)
    workflow_dir = next((tmp_path / "runs").iterdir())  # single workflow-id dir
    return next(workflow_dir.iterdir())  # single run dir


def test_cost_events_aggregate_into_video_json(tmp_path: Path) -> None:
    run_dir = _run(STUBS / "emits_cost", tmp_path)
    video = read_video(run_dir / "01")
    assert video.status == "complete"
    assert video.cost is not None
    # openrouter: 0.02 + 0.01, both non-cached → actual and uncached.
    assert video.cost["actual"]["openrouter"] == pytest.approx(0.03)
    assert video.cost["uncached"]["openrouter"] == pytest.approx(0.03)
    # higgsfield: single cached cost → uncached only, absent from actual.
    assert video.cost["uncached"]["higgsfield"] == pytest.approx(12)
    assert "higgsfield" not in video.cost["actual"]


def test_no_cost_events_records_no_cost_block(tmp_path: Path) -> None:
    run_dir = _run(STUBS / "succeeds", tmp_path)
    video = read_video(run_dir / "01")
    assert video.status == "complete"
    assert video.cost is None
