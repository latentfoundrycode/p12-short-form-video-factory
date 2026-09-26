"""TASK-SSN-C1 contract: the SSN workflow scaffold runs end-to-end in dry-run.

Driven through the REAL supervisor (subprocess-per-video, SDK runner, step cache) in dry-run at zero
cost, the scaffold must produce a valid house-format vertical `final.mp4` and a `complete` record --
proving the prepare()/run() pipeline is wired (agents/speech/graphics/finalize all stubbed in
dry-run). The scaffold's prepare() returns the `{"subjects": [...]}` shape (one per video) that C2
will fill with real distinct-subject selection; run() consumes `ctx.shared["subjects"][...]`.

Supervisor-authored frozen contract (RED-first); the builder creates the workflow folder.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sfvf._ffmpeg import probe

from app.core.env import EnvBlocked, EnvReady
from app.core.records import read_request, read_video
from app.core.supervisor import RunBusy, run_request

_WF = Path(__file__).resolve().parents[2] / "workflows" / "sensational-science-news"


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def test_scaffold_dry_run_produces_a_finished_video(tmp_path: Path) -> None:
    result = run_request(
        _WF,
        params={},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        cache_dir=tmp_path / "cache",
        ensure_env=_ready,
        dry_run=True,
    )
    assert not isinstance(result, EnvBlocked | RunBusy)

    run_dir = next((tmp_path / "runs" / "sensational-science-news").iterdir())
    assert read_request(run_dir).status == "complete"

    video = read_video(run_dir / "01")
    assert video.status == "complete"
    assert video.result is not None
    final = run_dir / "01" / video.result["video"]
    assert final.is_file()
    probed = probe(final)
    assert (probed.width, probed.height) == (1080, 1920)
    assert probed.duration_s > 0


def test_scaffold_prepare_returns_subjects_shape(tmp_path: Path) -> None:
    # prepare() runs once and returns one subject per video in ctx.shared["subjects"]; the shape is
    # what C2 fills with real distinct-subject selection. Verified via the shared payload the runner
    # persists for the video workers.
    run_request(
        _WF,
        params={},
        video_count=2,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        cache_dir=tmp_path / "cache",
        ensure_env=_ready,
        dry_run=True,
    )
    run_dir = next((tmp_path / "runs" / "sensational-science-news").iterdir())
    context = json.loads((run_dir / "01" / "context.json").read_text(encoding="utf-8"))
    subjects = context["shared"]["subjects"]
    assert isinstance(subjects, list) and len(subjects) == 2
