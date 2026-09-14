"""G-4 contract: the Learning tab's read — per-workflow quality-label counts (§8.5).

§8.5: "Lists every workflow together with how many quality labels have accumulated since its last
learning run. No minimum is imposed — the count is shown so the user can decide when there is enough
to be worth acting on."

`GET /api/learning` → `{"workflows": [{workflow_id, name, label_count, rules_count,
skills_count, last_learned}]}`, one row per registered workflow in folder-name order. A "label" is a
video whose `video.json` quality has at least one worded ANSWER (the raw material for learning,
§11.1); counted across all the workflow's runs. `rules_count`/`skills_count` are the workflow's
`rules/*.md` and `skills/*.md` file counts. `last_learned` is null until a learning run records one
(G-5) — for now the count is effectively all-time. No learning run is started here (that is G-5).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.layout import format_video_dir
from app.core.records import VideoRecord, create_request, write_video
from app.main import create_app
from tests.registry.fixtures import minimal_toml, write_plugin

FACTORS = '[[quality_factors]]\nkey = "hook"\nquestion = "Did it hook you?"'


def _seed_run(runs: Path, workflow_id: str, run_id: str, quality_by_index: dict[int, dict]) -> None:
    run_dir = runs / workflow_id / run_id
    run_dir.mkdir(parents=True)
    n = len(quality_by_index)
    create_request(
        run_dir,
        run_id=run_id,
        workflow={"id": workflow_id, "version": "1.0.0", "sdk": "1"},
        params={},
        videos=[{"index": i, "status": "complete"} for i in range(1, n + 1)],
        status="complete",
    )
    for i in range(1, n + 1):
        vdir = run_dir / format_video_dir(i, n)
        vdir.mkdir(parents=True, exist_ok=True)
        quality = quality_by_index.get(i)
        write_video(
            vdir,
            VideoRecord(
                index=i,
                status="complete",
                started_utc="t",
                ended_utc="t",
                quality=quality,
            ),
        )


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    runs = tmp_path / "runs"
    return TestClient(create_app(workflows_dir=workflows, runs_dir=runs)), tmp_path


def _rows(client: TestClient) -> list[dict]:
    response = client.get("/api/learning")
    assert response.status_code == 200
    return response.json()["workflows"]


def test_empty_when_no_workflows(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert _rows(client) == []


def test_row_shape_and_folder_order(tmp_path: Path) -> None:
    client, base = _client(tmp_path)
    write_plugin(base / "workflows", "zeta", minimal_toml("zeta", extra=FACTORS))
    write_plugin(base / "workflows", "alpha", minimal_toml("alpha", extra=FACTORS))
    rows = _rows(client)
    assert [r["workflow_id"] for r in rows] == ["alpha", "zeta"]
    assert set(rows[0]) == {
        "workflow_id",
        "name",
        "label_count",
        "rules_count",
        "skills_count",
        "last_learned",
    }
    assert rows[0]["label_count"] == 0
    assert rows[0]["last_learned"] is None


def test_label_count_counts_videos_with_answers(tmp_path: Path) -> None:
    client, base = _client(tmp_path)
    write_plugin(base / "workflows", "explainer", minimal_toml("explainer", extra=FACTORS))
    runs = base / "runs"
    # Run A: videos 1 and 2 answered; video 3 has only a verdict (no answer → not a label).
    _seed_run(
        runs,
        "explainer",
        "20260914-100000",
        {
            1: {"answers": {"hook": "strong"}},
            2: {"answers": {"hook": "weak"}},
            3: {"accepted": True},
        },
    )
    # Run B: video 1 answered; video 2 has no quality at all.
    _seed_run(
        runs,
        "explainer",
        "20260914-110000",
        {1: {"answers": {"hook": "ok"}}, 2: None},
    )
    row = next(r for r in _rows(client) if r["workflow_id"] == "explainer")
    assert row["label_count"] == 3  # 2 from A + 1 from B (verdict-only and empty excluded)


def test_rules_and_skills_counts(tmp_path: Path) -> None:
    client, base = _client(tmp_path)
    write_plugin(
        base / "workflows",
        "explainer",
        minimal_toml("explainer", extra=FACTORS),
        extra_files={
            "rules/tone.md": "---\nagents: [scriptwriter]\n---\nBe concrete.",
            "rules/hooks.md": "---\n---\nOpen on an object.",
            "skills/composition.md": "# Composition patterns",
        },
    )
    row = next(r for r in _rows(client) if r["workflow_id"] == "explainer")
    assert row["rules_count"] == 2
    assert row["skills_count"] == 1


def test_workflow_without_rules_or_runs_is_zeroed(tmp_path: Path) -> None:
    client, base = _client(tmp_path)
    write_plugin(base / "workflows", "explainer", minimal_toml("explainer", extra=FACTORS))
    row = next(r for r in _rows(client) if r["workflow_id"] == "explainer")
    assert row["label_count"] == 0
    assert row["rules_count"] == 0
    assert row["skills_count"] == 0
    assert row["last_learned"] is None
