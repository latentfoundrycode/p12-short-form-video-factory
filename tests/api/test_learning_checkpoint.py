"""G-7e contract: the "since the last learning run" checkpoint (Architecture §5.11).

§5.11: "gather every `video.json` containing quality answers **since the last learning run**, load
that workflow's criteria files together with its current rules and skills, and run the
SkillOpt-derived optimiser to propose bounded edits."

Accepting a learning run records a per-workflow marker (the run's time). A later run gathers only
the labels from Generation Requests that STARTED after that marker, and `GET /api/learning` surfaces
the real `last_learned` (until now always null) and counts only labels since it. The marker lives
outside the workflow tree (learning may only write rules/skills/archive inside a workflow), in the
injected `learning_state_dir`. Known limitation (tracked): filtering is by request start time, so a
quality answer added to an OLDER request after a learning run is not re-counted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.core.layout import format_video_dir
from app.core.records import VideoRecord, create_request, write_video
from app.learning.engine import LearningInput, ProposedEdit
from app.learning.state import read_last_learned, write_last_learned
from app.main import create_app
from tests.registry.fixtures import minimal_toml, write_plugin

_RUN_OLD = ("20260101-000000", "2026-01-01T00:00:00Z")
_RUN_NEW = ("20260601-000000", "2026-06-01T00:00:00Z")


def _labeled_run(runs: Path, run_id: str, started_utc: str) -> None:
    run_dir = runs / "explainer" / run_id
    run_dir.mkdir(parents=True)
    create_request(
        run_dir,
        run_id=run_id,
        workflow={"id": "explainer", "version": "1.0.0", "sdk": "1"},
        params={},
        videos=[{"index": 1, "status": "complete"}],
        status="complete",
    )
    # create_request stamps started_utc from the clock; pin it to the fixture's chosen value.
    request_path = run_dir / "request.json"
    data = json.loads(request_path.read_text(encoding="utf-8"))
    data["started_utc"] = started_utc
    request_path.write_text(json.dumps(data), encoding="utf-8")
    video_dir = run_dir / format_video_dir(1, 1)
    video_dir.mkdir(parents=True, exist_ok=True)
    write_video(
        video_dir,
        VideoRecord(
            index=1,
            status="complete",
            started_utc=started_utc,
            ended_utc=started_utc,
            quality={"answers": {"hook": f"note-{run_id}"}},
        ),
    )


def _capturing_factory(captured: list[LearningInput], edits: list[Any] | None = None) -> Any:
    def factory(workflow_id: str, run_id: str) -> Any:
        def optimize(learning_input: LearningInput) -> list[Any]:
            captured.append(learning_input)
            return list(edits or [])

        return optimize

    return factory


def _setup(tmp_path: Path, *, factory: Any) -> tuple[TestClient, Path]:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    write_plugin(
        workflows,
        "explainer",
        minimal_toml("explainer"),
        extra_files={
            "rules/tone.md": "---\nversion: 1\n---\nBe concrete.",
            "skills/hooks.md": "# Hooks\nOpen on motion.",
        },
    )
    runs = tmp_path / "runs"
    runs.mkdir()
    for run_id, started in (_RUN_OLD, _RUN_NEW):
        _labeled_run(runs, run_id, started)
    state_dir = tmp_path / "learning-state"
    app = create_app(
        workflows_dir=workflows,
        runs_dir=runs,
        learning_staging_dir=tmp_path / "staging",
        learning_state_dir=state_dir,
        make_learning_optimizer=factory,
    )
    return TestClient(app), state_dir


def _row(client: TestClient) -> dict[str, Any]:
    rows = client.get("/api/learning").json()["workflows"]
    return next(row for row in rows if row["workflow_id"] == "explainer")


def test_no_marker_lists_null_last_learned_and_counts_all(tmp_path: Path) -> None:
    client, _state = _setup(tmp_path, factory=_capturing_factory([]))
    row = _row(client)
    assert row["last_learned"] is None
    assert row["label_count"] == 2  # both labelled runs counted


def test_run_without_marker_gathers_all_labels(tmp_path: Path) -> None:
    captured: list[LearningInput] = []
    client, _state = _setup(tmp_path, factory=_capturing_factory(captured))
    assert client.post("/api/learning/explainer/run").status_code == 200
    assert len(captured) == 1
    run_ids = sorted(str(label["run_id"]) for label in captured[0].labels)
    assert run_ids == [_RUN_OLD[0], _RUN_NEW[0]]


def test_run_with_marker_gathers_only_newer_labels(tmp_path: Path) -> None:
    captured: list[LearningInput] = []
    client, state_dir = _setup(tmp_path, factory=_capturing_factory(captured))
    write_last_learned(state_dir, "explainer", "2026-03-01T00:00:00Z")  # between old and new
    assert client.post("/api/learning/explainer/run").status_code == 200
    labels = captured[0].labels
    assert [str(label["run_id"]) for label in labels] == [_RUN_NEW[0]]  # only the newer request


def test_list_counts_only_labels_since_marker(tmp_path: Path) -> None:
    client, state_dir = _setup(tmp_path, factory=_capturing_factory([]))
    write_last_learned(state_dir, "explainer", "2026-03-01T00:00:00Z")
    row = _row(client)
    assert row["last_learned"] == "2026-03-01T00:00:00Z"  # surfaced verbatim
    assert row["label_count"] == 1  # only the newer request is counted


def test_accept_sets_last_learned_marker(tmp_path: Path) -> None:
    captured: list[LearningInput] = []
    # the run proposes one edit so accept has something to apply and commit
    factory = _capturing_factory(
        captured,
        edits=[ProposedEdit("rules/tone.md", "---\nversion: 1\n---\nOpen on an object.")],
    )
    client, state_dir = _setup(tmp_path, factory=factory)
    assert read_last_learned(state_dir, "explainer") is None  # no marker yet
    client.post("/api/learning/explainer/run")
    assert client.post("/api/learning/explainer/accept").status_code == 200
    marker = read_last_learned(state_dir, "explainer")
    assert marker is not None  # accept recorded the learning-run marker
    # the marker (now) is newer than both fixture runs, so nothing counts as new anymore
    assert _row(client)["label_count"] == 0
    assert _row(client)["last_learned"] == marker


def test_accept_without_applied_edits_does_not_advance_marker(tmp_path: Path) -> None:
    # A no-op accept (a run that proposed nothing, so nothing is applied) must NOT advance the
    # checkpoint — otherwise existing labels would be hidden from future learning with no work done.
    # the optimiser proposes nothing, so the run stages nothing to accept
    client, state_dir = _setup(tmp_path, factory=_capturing_factory([]))
    client.post("/api/learning/explainer/run")
    assert client.post("/api/learning/explainer/accept").status_code == 200
    assert read_last_learned(state_dir, "explainer") is None  # marker untouched
    assert _row(client)["label_count"] == 2  # both labels still counted as unlearned
