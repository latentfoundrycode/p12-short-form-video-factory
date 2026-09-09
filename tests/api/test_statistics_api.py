"""Contract: GET /api/statistics returns per-meter monthly spend (PRD §8.6).

The route delegates to `aggregate_statistics` with the app's runs dir and the current UTC time, so
fixtures are dated in the current month to fall inside the window. `months` is clamped to [1, MAX].
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.statistics import DEFAULT_MONTHS, MAX_MONTHS
from app.core.records import write_json_atomic
from app.main import create_app


def _client(tmp_path: Path) -> TestClient:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    return TestClient(create_app(workflows_dir=workflows_dir, runs_dir=tmp_path / "runs"))


def _seed_this_month(runs_dir: Path, meter: str, amount: float) -> None:
    now = datetime.now(UTC)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    run_dir = runs_dir / "wf" / "run-1"
    write_json_atomic(
        run_dir / "request.json",
        {
            "run_id": "run-1",
            "workflow": {"id": "wf", "version": "1", "sdk": "1"},
            "started_utc": stamp,
            "ended_utc": stamp,
            "status": "complete",
            "params": {},
            "params_locked_utc": stamp,
            "dry_run": False,
            "videos": [{"index": 1, "status": "complete"}],
        },
    )
    write_json_atomic(
        run_dir / "01" / "video.json",
        {
            "index": 1,
            "status": "complete",
            "started_utc": stamp,
            "ended_utc": stamp,
            "cost": {"actual": {meter: amount}},
        },
    )


def test_empty_returns_no_series(tmp_path: Path) -> None:
    resp = _client(tmp_path).get("/api/statistics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["months"] == DEFAULT_MONTHS
    assert body["series"] == []


def test_shape_of_a_fiat_series(tmp_path: Path) -> None:
    _seed_this_month(tmp_path / "runs", "openrouter", 0.42)
    resp = _client(tmp_path).get("/api/statistics")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["series"]) == 1
    fiat = body["series"][0]
    assert fiat["id"] == "fiat"
    assert fiat["kind"] == "fiat"
    assert fiat["unit"] == "usd"
    assert fiat["providers"] == ["OpenRouter"]
    assert fiat["total"] == 0.42
    assert len(fiat["buckets"]) == DEFAULT_MONTHS
    assert fiat["buckets"][-1]["amount"] == 0.42  # current month is the last bucket


def test_months_query_is_honoured_and_clamped(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/api/statistics?months=3").json()["months"] == 3
    # Below 1 clamps to 1; above the max clamps to MAX_MONTHS.
    assert client.get("/api/statistics?months=0").json()["months"] == 1
    assert client.get("/api/statistics?months=9999").json()["months"] == MAX_MONTHS
