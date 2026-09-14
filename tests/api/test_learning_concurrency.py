"""H44 contract: serialize learning operations per workflow + clean accept error mapping.

Concurrent learning ops on the same workflow race on that workflow's staging directory
(`run_learning` does rmtree+mkdir+write), so run/run or run/accept could clobber each other's
proposals or make two paid calls. Serialize them with a per-workflow lock held across run/accept/
reject. Spend is already ceiling-bounded by the BudgetGuard; this closes the staging race and the
double-run. Also: `accept_learning` can raise `AcceptError` (an internal learning-state failure);
the accept endpoint must surface it as a clean 502, not a bare 500.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.learning import _workflow_lock
from app.learning.accept import AcceptError
from app.learning.engine import LearningInput, ProposedEdit
from app.main import create_app
from tests.registry.fixtures import minimal_toml, write_plugin


def _stub_factory(edits: list[ProposedEdit] | None = None) -> Any:
    def factory(workflow_id: str, run_id: str) -> Any:
        def optimize(_learning_input: LearningInput) -> list[ProposedEdit]:
            return list(edits or [])

        return optimize

    return factory


def _setup(tmp_path: Path, *, factory: Any) -> TestClient:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    write_plugin(
        workflows,
        "explainer",
        minimal_toml("explainer"),
        extra_files={"rules/tone.md": "---\nversion: 1\n---\nBe concrete."},
    )
    runs = tmp_path / "runs"
    runs.mkdir()
    app = create_app(
        workflows_dir=workflows,
        runs_dir=runs,
        learning_staging_dir=tmp_path / "staging",
        learning_state_dir=tmp_path / "learning-state",
        make_learning_optimizer=factory,
    )
    return TestClient(app)


def test_workflow_lock_is_stable_per_id() -> None:
    assert _workflow_lock("explainer") is _workflow_lock("explainer")  # same id -> same lock
    assert _workflow_lock("explainer") is not _workflow_lock("other")  # different id -> different


def test_run_holds_the_workflow_lock_during_the_run(tmp_path: Path) -> None:
    # While run_learning executes, the endpoint holds the workflow's (non-reentrant) lock, so a
    # non-blocking acquire from inside the injected optimiser must fail.
    observed: dict[str, bool] = {}

    def factory(workflow_id: str, run_id: str) -> Any:
        def optimize(_learning_input: LearningInput) -> list[ProposedEdit]:
            lock = _workflow_lock(workflow_id)
            got = lock.acquire(blocking=False)
            observed["held_by_endpoint"] = not got
            if got:  # should not happen; release so we never deadlock the suite
                lock.release()
            return []

        return optimize

    client = _setup(tmp_path, factory=factory)
    assert client.post("/api/learning/explainer/run").status_code == 200
    assert observed["held_by_endpoint"] is True


def test_accept_error_maps_to_502(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup(tmp_path, factory=_stub_factory())

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise AcceptError("staging/workflow overlap")

    monkeypatch.setattr("app.api.learning.accept_learning", boom)
    assert client.post("/api/learning/explainer/accept").status_code == 502


def test_accept_and_reject_still_work_under_the_lock(tmp_path: Path) -> None:
    # The lock must not break the normal sequential flow.
    client = _setup(tmp_path, factory=_stub_factory([ProposedEdit("rules/tone.md", "new")]))
    assert client.post("/api/learning/explainer/run").status_code == 200
    assert client.post("/api/learning/explainer/accept").status_code == 200
    # a second run + reject also completes (lock released after each op)
    assert client.post("/api/learning/explainer/run").status_code == 200
    assert client.post("/api/learning/explainer/reject").status_code == 200
