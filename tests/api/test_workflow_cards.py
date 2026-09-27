"""Frozen contract - F2a: main-tab card data (PRD §8.1) on GET /api/workflows.

Each WorkflowOut gains, computed per request from the runs dir:
  - avg_cost_per_meter: dict[str, float] - the mean cost by meter across the workflow's most-recent
    up-to-10 COUNTED runs (status complete/partial, non-dry). Each meter's total is divided by the
    number of counted runs (pool size), so a meter absent from some runs averages lower - "average
    cost per meter across the last ten runs" (R-005).
  - runs_counted: int - how many runs were averaged (0..10).
  - archived: bool - True for a synthetic card whose code folder is gone but whose run output
    remains, so its videos stay browsable (R-011); False for scanned workflows.

Failed/stopped/dry runs are excluded (mirrors the estimate history filter). No network, no spend.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    prepare: dict[str, float] | None = None,
) -> None:
    run_dir = runs_dir / workflow_id / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    request = {
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
    if prepare is not None:
        request["prepare_cost"] = {"actual": dict(prepare), "uncached": dict(prepare)}
    (run_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")
    for i, cost in enumerate(videos):
        vdir = run_dir / f"{i:02d}"
        vdir.mkdir(parents=True, exist_ok=True)
        video = {
            "index": i,
            "status": "complete",
            "started_utc": "2026-09-27T00:00:00Z",
            "ended_utc": "2026-09-27T00:00:30Z",
            "cost": {"actual": dict(cost), "uncached": dict(cost)},
        }
        (vdir / "video.json").write_text(json.dumps(video), encoding="utf-8")


def _card(body: dict, workflow_id: str) -> dict:
    return next(item for item in body["workflows"] if item["id"] == workflow_id)


def test_no_runs_defaults(tmp_path: Path) -> None:
    write_plugin(tmp_path / "wf", "alpha", minimal_toml("alpha"))
    body = _client(tmp_path / "wf", tmp_path / "runs").get("/api/workflows").json()
    card = _card(body, "alpha")
    assert card["avg_cost_per_meter"] == {}
    assert card["runs_counted"] == 0
    assert card["archived"] is False


def test_avg_cost_per_meter_over_runs(tmp_path: Path) -> None:
    write_plugin(tmp_path / "wf", "alpha", minimal_toml("alpha"))
    runs = tmp_path / "runs"
    _write_run(runs, "alpha", "20260927-000001", videos=[{"openrouter": 0.10, "byteplus": 2.00}])
    _write_run(runs, "alpha", "20260927-000002", videos=[{"openrouter": 0.30, "byteplus": 3.00}])
    card = _card(_client(tmp_path / "wf", runs).get("/api/workflows").json(), "alpha")
    assert card["runs_counted"] == 2
    assert card["avg_cost_per_meter"]["openrouter"] == 0.20
    assert card["avg_cost_per_meter"]["byteplus"] == 2.50


def test_meter_absent_from_some_runs_divides_by_pool_size(tmp_path: Path) -> None:
    # byteplus appears in only 1 of 2 counted runs -> averaged over pool size (2), not over 1.
    write_plugin(tmp_path / "wf", "alpha", minimal_toml("alpha"))
    runs = tmp_path / "runs"
    _write_run(runs, "alpha", "20260927-000001", videos=[{"openrouter": 0.10, "byteplus": 2.00}])
    _write_run(runs, "alpha", "20260927-000002", videos=[{"openrouter": 0.10}])
    card = _card(_client(tmp_path / "wf", runs).get("/api/workflows").json(), "alpha")
    assert card["runs_counted"] == 2
    assert card["avg_cost_per_meter"]["byteplus"] == 1.00


def test_prepare_cost_counted(tmp_path: Path) -> None:
    write_plugin(tmp_path / "wf", "alpha", minimal_toml("alpha"))
    runs = tmp_path / "runs"
    _write_run(
        runs,
        "alpha",
        "20260927-000001",
        videos=[{"openrouter": 0.10}],
        prepare={"openrouter": 0.04},
    )
    card = _card(_client(tmp_path / "wf", runs).get("/api/workflows").json(), "alpha")
    assert card["runs_counted"] == 1
    assert card["avg_cost_per_meter"]["openrouter"] == 0.14


def test_excludes_failed_and_dry_runs(tmp_path: Path) -> None:
    write_plugin(tmp_path / "wf", "alpha", minimal_toml("alpha"))
    runs = tmp_path / "runs"
    _write_run(runs, "alpha", "20260927-000001", videos=[{"openrouter": 1.00}])
    _write_run(runs, "alpha", "20260927-000002", videos=[{"openrouter": 9.00}], status="failed")
    _write_run(runs, "alpha", "20260927-000003", videos=[{"openrouter": 9.00}], dry_run=True)
    card = _card(_client(tmp_path / "wf", runs).get("/api/workflows").json(), "alpha")
    assert card["runs_counted"] == 1
    assert card["avg_cost_per_meter"]["openrouter"] == 1.00


def test_caps_at_ten_most_recent(tmp_path: Path) -> None:
    write_plugin(tmp_path / "wf", "alpha", minimal_toml("alpha"))
    runs = tmp_path / "runs"
    for n in range(1, 12):  # 11 runs
        _write_run(runs, "alpha", f"20260927-0000{n:02d}", videos=[{"openrouter": 1.00}])
    card = _card(_client(tmp_path / "wf", runs).get("/api/workflows").json(), "alpha")
    assert card["runs_counted"] == 10


def test_archived_card_for_output_without_code(tmp_path: Path) -> None:
    write_plugin(tmp_path / "wf", "alpha", minimal_toml("alpha"))
    runs = tmp_path / "runs"
    # "ghost" has run output but no folder under workflows/
    _write_run(runs, "ghost", "20260927-000001", videos=[{"openrouter": 0.50}])
    body = _client(tmp_path / "wf", runs).get("/api/workflows").json()
    ids = {item["id"] for item in body["workflows"]}
    assert "ghost" in ids
    ghost = _card(body, "ghost")
    assert ghost["archived"] is True
    assert ghost["valid"] is False
    assert ghost["avg_cost_per_meter"]["openrouter"] == 0.50
    # a live workflow is not archived
    assert _card(body, "alpha")["archived"] is False


def test_archived_workflow_runs_stay_browsable(tmp_path: Path) -> None:
    write_plugin(tmp_path / "wf", "alpha", minimal_toml("alpha"))
    runs = tmp_path / "runs"
    _write_run(runs, "ghost", "20260927-000001", videos=[{"openrouter": 0.50}])
    resp = _client(tmp_path / "wf", runs).get("/api/workflows/ghost/runs")
    assert resp.status_code == 200


def test_drive_relative_workflow_id_is_rejected(tmp_path: Path) -> None:
    # A Windows drive-relative id (e.g. "C:") must never be accepted by the browsable read route,
    # since `runs_dir / "C:"` would escape to the drive root.
    write_plugin(tmp_path / "wf", "alpha", minimal_toml("alpha"))
    client = _client(tmp_path / "wf", tmp_path / "runs")
    for bad in ("C:", "D:"):
        assert client.get(f"/api/workflows/{bad}/runs").status_code == 404, bad
