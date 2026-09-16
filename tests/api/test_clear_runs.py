"""Contract: delete a run + clear failed runs (Runs list cleanup, owner-approved).

The Runs list needs a per-run Delete and a bulk "Clear failed". Both HARD-delete run directories
(permanent, behind a UI confirm). Safety rules:
- Only a registered workflow's own runs may be touched (`_require_workflow` + safe run-id segment).
- A run that is still `running` is NEVER deleted (its process owns that directory) — per-run delete
  refuses it with 409; clear-failed only ever targets terminal failed/stopped states.
- `DELETE /api/workflows/{workflow_id}/runs/{run_id}` removes exactly that run dir.
- `POST /api/workflows/{workflow_id}/runs/clear-failed` removes every run whose status is
  `failed`, `stopped`, or `stopped-budget` (the disposable terminal states), leaving `complete`,
  `partial`, and `running` runs untouched, and returns the deleted run ids.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.records import create_request
from app.main import create_app
from tests.registry.fixtures import minimal_toml, write_plugin


def _seed_run(runs: Path, workflow_id: str, run_id: str, status: str) -> Path:
    run_dir = runs / workflow_id / run_id
    run_dir.mkdir(parents=True)
    create_request(
        run_dir,
        run_id=run_id,
        workflow={"id": workflow_id, "version": "1.0.0", "sdk": "1"},
        params={},
        videos=[{"index": 1, "status": "complete"}],
        status=status,  # type: ignore[arg-type]
    )
    return run_dir


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    write_plugin(workflows, "explainer", minimal_toml("explainer"))
    runs = tmp_path / "runs"
    client = TestClient(create_app(workflows_dir=workflows, runs_dir=runs))
    return client, runs


def test_delete_run_removes_only_that_dir(tmp_path: Path) -> None:
    client, runs = _client(tmp_path)
    doomed = _seed_run(runs, "explainer", "20260916-100000", "failed")
    keeper = _seed_run(runs, "explainer", "20260916-110000", "complete")

    response = client.delete("/api/workflows/explainer/runs/20260916-100000")
    assert response.status_code == 200
    assert response.json()["deleted"] == "20260916-100000"
    assert not doomed.exists()  # the run dir is gone from disk
    assert keeper.exists()  # the other run is untouched


def test_delete_run_404_when_missing(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.delete("/api/workflows/explainer/runs/20260916-100000").status_code == 404


def test_delete_run_404_for_unknown_workflow(tmp_path: Path) -> None:
    client, runs = _client(tmp_path)
    _seed_run(runs, "explainer", "20260916-100000", "failed")
    assert client.delete("/api/workflows/nope/runs/20260916-100000").status_code == 404


def test_delete_run_rejects_unsafe_run_id(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.delete("/api/workflows/explainer/runs/..%2Fevil").status_code == 404


def test_delete_refuses_running_run(tmp_path: Path) -> None:
    # A running run owns its directory — deleting it would corrupt an active process.
    client, runs = _client(tmp_path)
    active = _seed_run(runs, "explainer", "20260916-120000", "running")
    response = client.delete("/api/workflows/explainer/runs/20260916-120000")
    assert response.status_code == 409
    assert active.exists()  # untouched


def test_clear_failed_deletes_failed_and_stopped_only(tmp_path: Path) -> None:
    client, runs = _client(tmp_path)
    failed = _seed_run(runs, "explainer", "20260916-100000", "failed")
    stopped = _seed_run(runs, "explainer", "20260916-101000", "stopped")
    budget = _seed_run(runs, "explainer", "20260916-102000", "stopped-budget")
    complete = _seed_run(runs, "explainer", "20260916-103000", "complete")
    partial = _seed_run(runs, "explainer", "20260916-104000", "partial")
    running = _seed_run(runs, "explainer", "20260916-105000", "running")

    response = client.post("/api/workflows/explainer/runs/clear-failed")
    assert response.status_code == 200
    deleted = response.json()["deleted"]
    assert set(deleted) == {"20260916-100000", "20260916-101000", "20260916-102000"}
    assert not failed.exists() and not stopped.exists() and not budget.exists()
    assert complete.exists() and partial.exists() and running.exists()  # kept


def test_clear_failed_with_nothing_to_clear_is_empty(tmp_path: Path) -> None:
    client, runs = _client(tmp_path)
    _seed_run(runs, "explainer", "20260916-100000", "complete")
    response = client.post("/api/workflows/explainer/runs/clear-failed")
    assert response.status_code == 200
    assert response.json()["deleted"] == []
