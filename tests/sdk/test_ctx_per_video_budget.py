"""TASK-SSN-B2 contract: ctx wires the per-video ceiling into reserve.

`ctx._budget_reserve` passes `ctx.video_index` and the per-video ceiling `ctx.per_video_budget`
(a run setting from B1) to the guard, so a cross-meter breach for the current video is refused. A
released reserve (the `_budget_reserved` context manager on an exception) frees the aggregate, so
Issue 6 (reserve/release-on-failure) is not regressed.

Supervisor-authored frozen contract (RED-first); the builder implements sdk/sfvf/context.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sfvf._budget import BudgetError
from sfvf.context import BudgetConfig, Context, ContextFile, ContextPaths


def _ctx(tmp: Path, *, per_video_budget: float | None, video_index: int) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=False,
            secrets={},
            video_index=video_index,
            per_video_budget=per_video_budget,
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
            budget=BudgetConfig(
                ledger_path=tmp / "budget" / "ledger.jsonl",
                estimates={"openrouter": 5.0, "serpapi": 5.0},
            ),
        )
    )


def test_ctx_reserve_refuses_cross_meter_per_video_breach(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, per_video_budget=8.0, video_index=1)
    ctx._budget_reserve("openrouter", "usd")  # reserves 5.0 for video 1
    with pytest.raises(BudgetError):
        ctx._budget_reserve("serpapi", "usd")  # 5.0 + 5.0 = 10.0 across meters > 8.0


def test_ctx_reserve_allows_within_per_video_budget(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, per_video_budget=12.0, video_index=1)
    ctx._budget_reserve("openrouter", "usd")  # 5.0
    ctx._budget_reserve("serpapi", "usd")  # 5.0 + 5.0 = 10.0 <= 12.0


def test_ctx_released_reserve_frees_per_video_aggregate(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, per_video_budget=8.0, video_index=1)
    with pytest.raises(RuntimeError), ctx._budget_reserved("openrouter", "usd"):  # reserves 5.0
        raise RuntimeError("provider failed")
    # The reserve was released on the exception, so a fresh 5.0 still fits under 8.0.
    ctx._budget_reserve("serpapi", "usd")


def test_ctx_no_per_video_budget_does_not_cap_cross_meter(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, per_video_budget=None, video_index=1)
    ctx._budget_reserve("openrouter", "usd")
    ctx._budget_reserve("serpapi", "usd")  # no per-video cap -> allowed
