"""Frozen contract — Stage P hardening: a FAILED paid call must release its budget reserve.

Observed at the P-B live smoke (2026-09-20): when a provider call failed after the SDK had already
RESERVED a conservative estimate, the reserve was never released. The "reserved" ledger entry
lingered, and because a token's effective spend falls back to its reserved amount when no "actual"
was recorded (sfvf._budget._TokenState.effective_amount), it kept counting toward the per-day
ceiling. Repeated failures accumulate and can eventually block legitimate runs / overstate use.

The reserve -> call -> reconcile path must RELEASE the reserve (reconcile to 0, note "released")
when the call raises, so a failed run contributes nothing to the ledger's day total.

No live network: the adapter is monkeypatched to raise; only the budget ledger under tmp is used.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sfvf._runtime import reset_active, set_active
from sfvf.context import BudgetConfig, Context, ContextFile, ContextPaths
from sfvf.media import video


def _ledger(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _ctx(tmp: Path, meter: str) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=False,
            secrets={"MINIMAX_API_KEY": "mm-fake-not-real"},
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
            budget=BudgetConfig(
                ledger_path=tmp / "budget" / "ledger.jsonl",
                per_run={meter: 100.0},
                per_day={meter: 100.0},
                estimates={},
            ),
        )
    )


def test_a_failed_paid_call_releases_its_budget_reserve(tmp_path: Path, monkeypatch) -> None:
    ledger_path = tmp_path / "budget" / "ledger.jsonl"
    ctx = _ctx(tmp_path, "minimax")

    import sfvf.providers.minimax as mm

    def _boom(*_a: object, **_k: object):
        raise RuntimeError("provider exploded mid-call")

    monkeypatch.setattr(mm, "generate_video", _boom)

    token = set_active(ctx)
    try:
        with pytest.raises(RuntimeError):
            video.generate("a wave", model="minimax/hailuo-h3", duration_s=4.0)
    finally:
        reset_active(token)

    lines = _ledger(ledger_path)
    reserved = [x for x in lines if x.get("kind") == "reserved"]
    assert reserved, "expected the call to reserve before failing"
    tok = reserved[-1]["token"]
    released = [
        x
        for x in lines
        if x.get("token") == tok and x.get("kind") == "actual" and x.get("amount") == 0.0
    ]
    assert released, (
        "a failed paid call must RELEASE its reserve (reconcile to 0), not leak it toward per_day"
    )
