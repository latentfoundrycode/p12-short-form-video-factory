"""A-7 capstone: the example workflow runs end-to-end and produces a real video.

This is Stage A's integration proof. The `explainer` example workflow (`workflows/explainer/`)
uses the whole provided-functions surface — research + llm (agents), speech, graphics
render/captions/safe_zone_css, and the mandatory finalize — and is driven through the REAL
supervisor (subprocess-per-video, the SDK runner, the step cache) in dry-run. At zero cost it
must yield a valid house-format `final.mp4` and a `complete` record. It is GATE-FREE
(`ctx.gate` is deferred to Stage F), so it runs unattended to completion.
"""

import sys
from pathlib import Path

from sfvf._ffmpeg import probe

from app.core.env import EnvBlocked, EnvReady
from app.core.records import read_events, read_request, read_video
from app.core.supervisor import RunBusy, run_request

EXPLAINER = Path(__file__).resolve().parents[2] / "workflows" / "explainer"


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def test_example_workflow_produces_a_finished_video(tmp_path: Path) -> None:
    result = run_request(
        EXPLAINER,
        params={"topic": "photosynthesis", "duration_s": 30, "voice": "narrator"},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        cache_dir=tmp_path / "cache",
        ensure_env=_ready,
        dry_run=True,
    )
    assert not isinstance(result, EnvBlocked | RunBusy)

    run_dir = next((tmp_path / "runs" / "explainer").iterdir())
    request = read_request(run_dir)
    assert request.status == "complete"

    video = read_video(run_dir / "01")
    assert video.status == "complete"
    assert video.result is not None
    assert video.result["video"] == "final.mp4"

    # The finished file is a real, valid, house-format vertical video.
    final = run_dir / "01" / "final.mp4"
    assert final.is_file()
    probed = probe(final)
    assert (probed.width, probed.height) == (1080, 1920)
    assert probed.duration_s > 0

    # The pipeline actually ran its cached steps (not merely emitted a result).
    step_names = {
        event.get("name")
        for _ts, _source, event in read_events(run_dir)
        if event.get("t") == "step"
    }
    assert {"script", "speech", "render"} <= step_names


def test_example_workflow_caches_across_runs(tmp_path: Path) -> None:
    # A second dry run against the same cache must reuse the step results: every
    # step reports "cached" and no step re-executes.
    cache_dir = tmp_path / "cache"
    for _ in range(2):
        run_request(
            EXPLAINER,
            params={"topic": "photosynthesis", "duration_s": 30, "voice": "narrator"},
            video_count=1,
            concurrency=1,
            runs_dir=tmp_path / "runs",
            cache_dir=cache_dir,
            ensure_env=_ready,
            dry_run=True,
        )

    runs = sorted((tmp_path / "runs" / "explainer").iterdir())
    assert len(runs) == 2
    second_steps = [
        event for _ts, _source, event in read_events(runs[1]) if event.get("t") == "step"
    ]
    assert second_steps
    assert all(event.get("status") == "cached" for event in second_steps)
