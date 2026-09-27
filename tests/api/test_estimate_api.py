"""Frozen contract - F3-1: POST /api/workflows/{id}/estimate returns a per-meter cost estimate.

The run form shows the estimated cost before launch (R-032, §7.3). The endpoint scales the per-video
uncached estimate by video_count and tags each meter with its unit/kind (H-CARDS-2 units).
Registry-only (you estimate what you can launch): an unknown workflow is 404.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.registry.fixtures import minimal_toml, write_plugin


def _client(workflows_dir: Path, runs_dir: Path) -> TestClient:
    return TestClient(create_app(workflows_dir, runs_dir=runs_dir))


def _write_run(
    runs_dir: Path,
    workflow_id: str,
    run_id: str,
    *,
    videos: list[dict[str, float]],
    status: str = "complete",
    dry_run: bool = False,
) -> None:
    run_dir = runs_dir / workflow_id / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "request.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "workflow": {"id": workflow_id, "version": "1.0.0", "sdk": "1"},
                "started_utc": "2026-09-27T00:00:00Z",
                "ended_utc": "2026-09-27T00:01:00Z",
                "status": status,
                "params": {},
                "params_locked_utc": "2026-09-27T00:00:00Z",
                "videos": [{"index": i, "status": "complete"} for i in range(len(videos))],
                "dry_run": dry_run,
            }
        ),
        encoding="utf-8",
    )
    for i, cost in enumerate(videos):
        vdir = run_dir / f"{i:02d}"
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "video.json").write_text(
            json.dumps(
                {
                    "index": i,
                    "status": "complete",
                    "started_utc": "2026-09-27T00:00:00Z",
                    "ended_utc": "2026-09-27T00:00:30Z",
                    "cost": {"actual": dict(cost), "uncached": dict(cost)},
                }
            ),
            encoding="utf-8",
        )


def test_estimate_no_history_is_none(tmp_path: Path) -> None:
    write_plugin(tmp_path / "wf", "alpha", minimal_toml("alpha"))
    resp = _client(tmp_path / "wf", tmp_path / "runs").post(
        "/api/workflows/alpha/estimate", json={"params": {}, "video_count": 1}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["confidence"] == "none"
    assert body["per_meter"] == {}
    assert body["matches"] == 0


def test_estimate_scales_by_video_count_with_units(tmp_path: Path) -> None:
    write_plugin(tmp_path / "wf", "alpha", minimal_toml("alpha"))
    runs = tmp_path / "runs"
    _write_run(runs, "alpha", "20260927-000001", videos=[{"openrouter": 0.10}])
    _write_run(runs, "alpha", "20260927-000002", videos=[{"openrouter": 0.10}])
    body = (
        _client(tmp_path / "wf", runs)
        .post("/api/workflows/alpha/estimate", json={"params": {}, "video_count": 2})
        .json()
    )
    assert body["confidence"] == "matched"
    assert body["matches"] == 2
    cell = body["per_meter"]["openrouter"]
    assert cell["unit"] == "usd"
    assert cell["kind"] == "fiat"
    assert cell["amount"] == pytest.approx(0.20)  # 0.10 per video * 2


def test_estimate_excludes_failed_and_dry(tmp_path: Path) -> None:
    write_plugin(tmp_path / "wf", "alpha", minimal_toml("alpha"))
    runs = tmp_path / "runs"
    _write_run(runs, "alpha", "20260927-000001", videos=[{"openrouter": 0.10}])
    _write_run(runs, "alpha", "20260927-000002", videos=[{"openrouter": 9.0}], status="failed")
    _write_run(runs, "alpha", "20260927-000003", videos=[{"openrouter": 9.0}], dry_run=True)
    body = (
        _client(tmp_path / "wf", runs)
        .post("/api/workflows/alpha/estimate", json={"params": {}, "video_count": 1})
        .json()
    )
    assert body["matches"] == 1
    assert body["per_meter"]["openrouter"]["amount"] == pytest.approx(0.10)


def test_estimate_unknown_workflow_is_404(tmp_path: Path) -> None:
    write_plugin(tmp_path / "wf", "alpha", minimal_toml("alpha"))
    resp = _client(tmp_path / "wf", tmp_path / "runs").post(
        "/api/workflows/ghost/estimate", json={"params": {}, "video_count": 1}
    )
    assert resp.status_code == 404
