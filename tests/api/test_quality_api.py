"""G-1 contract: quality capture — write worded answers + within-request rankings into video.json.

Architecture §9 / §11.1: "After a Generation Request finishes, the user writes a free-text answer to
each factor for every video, then ranks that request's videos against one another for each factor.
Accept or reject is recorded separately. There are no numeric ratings." §5.11: the learning process
later "gather[s] every `video.json` containing quality answers since the last learning run" — so the
answers, the per-factor ranking positions, and accept/reject must be persisted INTO each video.json
(the `VideoRecord.quality` field, which already exists but nothing populates yet).

This freezes `POST /api/workflows/{workflow_id}/runs/{run_id}/quality`:
  * body: `{"videos": [{"index", "answers"?, "accepted"?}, ...], "rankings": {factor: [idx, ...]}?}`
    — `answers` maps a declared factor key to free text; `rankings[factor]` is the request's video
    indices ordered best-first for that factor.
  * writes each video's `quality = {"answers"?, "accepted"?, "rankings"?}` where `rankings[factor]`
    is THIS video's 1-based position in that factor's ordered list (denormalised so the optimiser
    reads everything it needs from one video.json). Empty sub-parts are omitted.
  * validation (all → 422, nothing written): an unknown factor key in `answers` or `rankings`; a
    ranking list that is not a permutation of the request's video indices; a body video index not in
    the request. A non-terminal request → 409. Unknown workflow/run → 404.
Partial submissions are allowed (answer some factors / some videos; unanswered stays absent).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.layout import format_video_dir
from app.core.records import VideoRecord, create_request, read_video, write_video
from app.main import create_app
from tests.registry.fixtures import minimal_toml, write_plugin

FACTORS = (
    '[[quality_factors]]\nkey = "hook"\nquestion = "Did the first two seconds hook you? Why?"\n\n'
    '[[quality_factors]]\nkey = "pace"\nquestion = "Did the pace hold? Where did it sag?"'
)


def _setup(tmp_path: Path, *, status: str = "complete", n: int = 2) -> tuple[TestClient, Path, str]:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    write_plugin(workflows, "explainer", minimal_toml("explainer", extra=FACTORS))
    runs = tmp_path / "runs"
    run_id = "20260914-120000"
    run_dir = runs / "explainer" / run_id
    run_dir.mkdir(parents=True)
    videos = [{"index": i, "status": "complete"} for i in range(1, n + 1)]
    create_request(
        run_dir,
        run_id=run_id,
        workflow={"id": "explainer", "version": "1.0.0", "sdk": "1"},
        params={},
        videos=videos,
        status=status,  # type: ignore[arg-type]
    )
    for i in range(1, n + 1):
        vdir = run_dir / format_video_dir(i, n)
        vdir.mkdir(parents=True, exist_ok=True)
        write_video(
            vdir,
            VideoRecord(index=i, status="complete", started_utc="t", ended_utc="t"),
        )
    return TestClient(create_app(workflows_dir=workflows, runs_dir=runs)), run_dir, run_id


def _quality(run_dir: Path, index: int, n: int = 2) -> dict:
    return read_video(run_dir / format_video_dir(index, n)).quality or {}


def _post(client: TestClient, run_id: str, body: dict):
    return client.post(f"/api/workflows/explainer/runs/{run_id}/quality", json=body)


def test_answers_and_accept_written_into_video_json(tmp_path: Path) -> None:
    client, run_dir, run_id = _setup(tmp_path)
    body = {
        "videos": [
            {"index": 1, "answers": {"hook": "strong", "pace": "sagged mid"}, "accepted": True},
            {"index": 2, "answers": {"hook": "weak"}, "accepted": False},
        ]
    }
    assert _post(client, run_id, body).status_code == 200
    q1 = _quality(run_dir, 1)
    assert q1["answers"] == {"hook": "strong", "pace": "sagged mid"}
    assert q1["accepted"] is True
    q2 = _quality(run_dir, 2)
    assert q2["answers"] == {"hook": "weak"}
    assert q2["accepted"] is False


def test_ranking_positions_denormalised_per_video(tmp_path: Path) -> None:
    client, run_dir, run_id = _setup(tmp_path)
    # hook: video 2 is best, then video 1. pace: video 1 best, then video 2.
    body = {"videos": [], "rankings": {"hook": [2, 1], "pace": [1, 2]}}
    assert _post(client, run_id, body).status_code == 200
    assert _quality(run_dir, 1)["rankings"] == {"hook": 2, "pace": 1}
    assert _quality(run_dir, 2)["rankings"] == {"hook": 1, "pace": 2}


def test_partial_submission_is_allowed(tmp_path: Path) -> None:
    client, run_dir, run_id = _setup(tmp_path)
    body = {"videos": [{"index": 1, "answers": {"hook": "ok"}}]}
    assert _post(client, run_id, body).status_code == 200
    assert _quality(run_dir, 1)["answers"] == {"hook": "ok"}
    assert "accepted" not in _quality(run_dir, 1)
    assert _quality(run_dir, 2) == {}  # untouched


def test_unknown_answer_factor_is_422_and_writes_nothing(tmp_path: Path) -> None:
    client, run_dir, run_id = _setup(tmp_path)
    body = {"videos": [{"index": 1, "answers": {"nope": "x"}}]}
    assert _post(client, run_id, body).status_code == 422
    assert _quality(run_dir, 1) == {}


def test_unknown_ranking_factor_is_422(tmp_path: Path) -> None:
    client, _run_dir, run_id = _setup(tmp_path)
    assert _post(client, run_id, {"videos": [], "rankings": {"nope": [1, 2]}}).status_code == 422


def test_ranking_must_be_permutation_of_video_indices(tmp_path: Path) -> None:
    client, _run_dir, run_id = _setup(tmp_path)
    # duplicate index
    assert _post(client, run_id, {"videos": [], "rankings": {"hook": [1, 1]}}).status_code == 422
    # index not in the request (only 1,2 exist)
    assert _post(client, run_id, {"videos": [], "rankings": {"hook": [1, 3]}}).status_code == 422
    # incomplete (missing a video)
    assert _post(client, run_id, {"videos": [], "rankings": {"hook": [1]}}).status_code == 422


def test_body_video_index_must_exist(tmp_path: Path) -> None:
    client, _run_dir, run_id = _setup(tmp_path)
    body = {"videos": [{"index": 99, "answers": {"hook": "x"}}]}
    assert _post(client, run_id, body).status_code == 422


def test_non_terminal_request_is_409(tmp_path: Path) -> None:
    client, run_dir, run_id = _setup(tmp_path, status="running")
    body = {"videos": [{"index": 1, "answers": {"hook": "x"}}]}
    assert _post(client, run_id, body).status_code == 409
    assert _quality(run_dir, 1) == {}


def test_unknown_workflow_or_run_is_404(tmp_path: Path) -> None:
    client, _run_dir, run_id = _setup(tmp_path)
    ghost = client.post("/api/workflows/ghost/runs/x/quality", json={"videos": []})
    assert ghost.status_code == 404
    assert _post(client, "no-such-run", {"videos": []}).status_code == 404


def test_recorded_quality_surfaces_in_run_detail(tmp_path: Path) -> None:
    client, _run_dir, run_id = _setup(tmp_path)
    _post(client, run_id, {"videos": [{"index": 1, "answers": {"hook": "ok"}}]})
    detail = client.get(f"/api/workflows/explainer/runs/{run_id}").json()
    rec = next(v for v in detail["video_records"] if v["index"] == 1)
    assert rec["quality"]["answers"] == {"hook": "ok"}
