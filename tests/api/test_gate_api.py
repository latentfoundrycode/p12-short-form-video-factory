"""H-3 contract: the gate API — list pending gates + submit a decision (Architecture §3.5).

A workflow parked at `ctx.gate()` has emitted a `gate` event (recorded in the run's `events.jsonl`,
tagged with the video's dir as its source) and is polling `runs/<run>/<video>/gates/<token>.json`.
The frontend needs to (a) see which gates are still waiting and (b) write the user's decision to
that file — validated against the gate's declared shape, since the decision is user input.

- `GET /api/workflows/{id}/runs/{run_id}/gates` -> `{"gates": [{video, video_index, token, family,
  shape, prompt, ...}]}` — only gates with NO response file yet (an answered gate drops off).
- `POST /api/workflows/{id}/runs/{run_id}/gates` with `{"video", "token", "decision"}` validates the
  decision against the matching pending gate's shape and writes the response file atomically:
  approval -> choice in {approve, reject}; choice -> choice in the declared options; selection ->
  choice in {approve, reject} with keep/redo declared item ids. Unknown (video, token) -> 404; an
  invalid decision for the shape -> 400.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.layout import format_video_dir
from app.core.records import append_event, create_request
from app.main import create_app
from tests.registry.fixtures import minimal_toml, write_plugin

_RUN = "20260916-120000"


def _seed(tmp_path: Path) -> tuple[TestClient, Path]:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    write_plugin(workflows, "explainer", minimal_toml("explainer"))
    runs = tmp_path / "runs"
    run_dir = runs / "explainer" / _RUN
    run_dir.mkdir(parents=True)
    create_request(
        run_dir,
        run_id=_RUN,
        workflow={"id": "explainer", "version": "1.0.0", "sdk": "1"},
        params={},
        videos=[{"index": 1, "status": "running"}, {"index": 2, "status": "running"}],
        status="running",
    )
    v1 = format_video_dir(1, 2)
    v2 = format_video_dir(2, 2)
    (run_dir / v1).mkdir()
    (run_dir / v2).mkdir()
    # video 1: an approval gate, still pending (no response file)
    append_event(
        run_dir,
        {
            "t": "gate",
            "family": "approve-script",
            "token": "approve-script-0",
            "shape": "approval",
            "prompt": "Approve?",
        },
        source=v1,
    )
    # video 2: a choice gate, ALREADY answered (response file present) -> must NOT be listed
    append_event(
        run_dir,
        {
            "t": "gate",
            "family": "pick-tone",
            "token": "pick-tone-0",
            "shape": "choice",
            "prompt": "Tone?",
            "options": ["warm", "cool"],
        },
        source=v2,
    )
    (run_dir / v2 / "gates").mkdir()
    (run_dir / v2 / "gates" / "pick-tone-0.json").write_text('{"choice": "warm"}', encoding="utf-8")

    client = TestClient(create_app(workflows_dir=workflows, runs_dir=runs))
    return client, run_dir


def test_list_returns_only_pending_gates(tmp_path: Path) -> None:
    client, _ = _seed(tmp_path)
    response = client.get(f"/api/workflows/explainer/runs/{_RUN}/gates")
    assert response.status_code == 200
    gates = response.json()["gates"]
    assert [g["token"] for g in gates] == ["approve-script-0"]  # pick-tone-0 already answered
    gate = gates[0]
    assert gate["family"] == "approve-script"
    assert gate["shape"] == "approval"
    assert gate["prompt"] == "Approve?"
    assert gate["video"] == format_video_dir(1, 2)
    assert gate["video_index"] == 1


def test_list_404_for_unknown_run(tmp_path: Path) -> None:
    client, _ = _seed(tmp_path)
    assert client.get("/api/workflows/explainer/runs/nope/gates").status_code == 404


def test_submit_approval_writes_response_file(tmp_path: Path) -> None:
    client, run_dir = _seed(tmp_path)
    v1 = format_video_dir(1, 2)
    response = client.post(
        f"/api/workflows/explainer/runs/{_RUN}/gates",
        json={"video": v1, "token": "approve-script-0", "decision": {"choice": "approve"}},
    )
    assert response.status_code == 200
    written = json.loads((run_dir / v1 / "gates" / "approve-script-0.json").read_text("utf-8"))
    assert written["choice"] == "approve"
    # the gate now drops off the pending list
    gates = client.get(f"/api/workflows/explainer/runs/{_RUN}/gates").json()["gates"]
    assert gates == []


def test_submit_unknown_token_is_404(tmp_path: Path) -> None:
    client, _ = _seed(tmp_path)
    v1 = format_video_dir(1, 2)
    response = client.post(
        f"/api/workflows/explainer/runs/{_RUN}/gates",
        json={"video": v1, "token": "does-not-exist-0", "decision": {"choice": "approve"}},
    )
    assert response.status_code == 404


def test_submit_invalid_choice_for_approval_is_400(tmp_path: Path) -> None:
    # An approval gate accepts only approve/reject; a bogus choice is refused (user input).
    client, _ = _seed(tmp_path)
    v1 = format_video_dir(1, 2)
    response = client.post(
        f"/api/workflows/explainer/runs/{_RUN}/gates",
        json={"video": v1, "token": "approve-script-0", "decision": {"choice": "banana"}},
    )
    assert response.status_code == 400


def test_submit_rejects_unsafe_video_segment(tmp_path: Path) -> None:
    client, _ = _seed(tmp_path)
    response = client.post(
        f"/api/workflows/explainer/runs/{_RUN}/gates",
        json={"video": "../evil", "token": "approve-script-0", "decision": {"choice": "approve"}},
    )
    assert response.status_code in (400, 404)
