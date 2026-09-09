"""C-4 review hardening: two gaps the decorrelated review surfaced on the atomic pre-flight.

1. A DRY run spends nothing, so it must never be refused for budget — the pre-flight is skipped for
   dry runs (a dry preview of a run you cannot afford is exactly what dry mode is for).
2. `safety_factor` multiplies a cost estimate to build in headroom, so a value below 1.0 (or a
   non-finite one) would silently deflate the estimate and let the pre-flight under-refuse. The
   manifest schema rejects such values up front.

These lock review findings; they are not part of the frozen C-4 contract in test_preflight.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from sfvf.context import BudgetConfig

from app.core.env import EnvBlocked, EnvReady
from app.core.records import read_request, write_json_atomic
from app.core.supervisor import RunBusy, run_request
from app.registry.schema import WorkflowSection

_STUBS = Path(__file__).resolve().parent.parent / "stubs"


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def _seed_complete_run(
    runs_dir: Path, workflow_id: str, run_id: str, *, params: dict, uncached: dict[str, float]
) -> None:
    run_dir = runs_dir / workflow_id / run_id
    write_json_atomic(
        run_dir / "request.json",
        {
            "run_id": run_id,
            "workflow": {"id": workflow_id, "version": "1", "sdk": "1"},
            "started_utc": "2026-01-01T00:00:00Z",
            "ended_utc": "2026-01-01T00:01:00Z",
            "status": "complete",
            "params": params,
            "params_locked_utc": "2026-01-01T00:00:00Z",
            "dry_run": False,
            "videos": [{"index": 1, "status": "complete"}],
        },
    )
    write_json_atomic(
        run_dir / "01" / "video.json",
        {
            "index": 1,
            "status": "complete",
            "started_utc": "2026-01-01T00:00:00Z",
            "ended_utc": "2026-01-01T00:01:00Z",
            "cost": {"uncached": uncached},
        },
    )


def test_dry_atomic_run_is_not_refused_when_over_budget(tmp_path: Path) -> None:
    # Same unaffordable history as the frozen refusal test, but this launch is a DRY run: it
    # spends nothing, so the pre-flight is skipped and the run proceeds (not stopped-budget).
    runs = tmp_path / "runs"
    _seed_complete_run(
        runs, "atomic-free", "20260101-000000", params={"model": "A"}, uncached={"openrouter": 5.0}
    )
    budget = BudgetConfig(
        ledger_path=tmp_path / "budget" / "ledger.jsonl",
        kill_switch_path=None,
        per_run={"openrouter": 1.0},  # 5.0 would refuse a real run, but this one is dry
        per_day={"openrouter": 100.0},
        estimates={"openrouter": 0.05},
    )
    result = run_request(
        _STUBS / "atomic_free",
        params={"model": "A"},
        video_count=1,
        concurrency=1,
        runs_dir=runs,
        ensure_env=_ready,
        budget=budget,
        dry_run=True,
    )
    assert not isinstance(result, EnvBlocked | RunBusy)
    launched = [d for d in (runs / "atomic-free").iterdir() if d.name != "20260101-000000"]
    assert len(launched) == 1
    request = read_request(launched[0])
    assert request.status != "stopped-budget"
    assert all(v.status != "stopped" for v in request.videos)


def _workflow(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "wf",
        "name": "WF",
        "version": "1.0.0",
        "entrypoint": "main:run",
        "sdk": "1",
        "atomic": True,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("bad", [0.0, -1.0, 0.5, float("nan"), float("inf")])
def test_invalid_safety_factor_is_rejected(bad: float) -> None:
    with pytest.raises(ValidationError):
        WorkflowSection.model_validate(_workflow(safety_factor=bad))


@pytest.mark.parametrize("good", [1.0, 1.5, 2.0])
def test_valid_safety_factor_is_accepted(good: float) -> None:
    section = WorkflowSection.model_validate(_workflow(safety_factor=good))
    assert section.safety_factor == good


def test_safety_factor_may_be_omitted() -> None:
    section = WorkflowSection.model_validate(_workflow())
    assert section.safety_factor is None
