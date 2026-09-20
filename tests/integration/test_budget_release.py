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


def test_a_post_call_io_failure_records_the_real_cost_not_a_release(
    tmp_path: Path, monkeypatch
) -> None:
    # If the paid call SUCCEEDS (the provider has billed) but a LATER local step fails (e.g. the
    # artifact write), the REAL cost must be reconciled — not released to 0. Otherwise a
    # bills-then-local-IO-fails loop spends real money while the per-day ledger stays ~0 and the
    # ceiling never trips. So the reserved region must cover only the paid call; the cost is
    # reconciled as soon as the adapter returns, before any filesystem write.
    import pathlib

    from sfvf.providers.base import Cost, Output

    ledger_path = tmp_path / "budget" / "ledger.jsonl"
    ctx = _ctx(tmp_path, "minimax")

    import sfvf.providers.minimax as mm

    def _ok(*_a: object, **_k: object):
        return Output(data=b"MP4-BYTES", media_type="video/mp4"), Cost(
            amount=0.20, source="metered"
        )

    monkeypatch.setattr(mm, "generate_video", _ok)

    # The paid call succeeds; the subsequent artifact write (a .mp4) fails.
    real_write = pathlib.Path.write_bytes

    def _boom_write(self: pathlib.Path, data: object) -> int:
        if str(self).endswith(".mp4"):
            raise OSError("disk full")
        return real_write(self, data)  # leave the ledger's own writes untouched

    monkeypatch.setattr(pathlib.Path, "write_bytes", _boom_write)

    token = set_active(ctx)
    try:
        with pytest.raises(OSError):
            video.generate("a wave", model="minimax/hailuo-h3", duration_s=4.0)
    finally:
        reset_active(token)

    lines = _ledger(ledger_path)
    reserved = [x for x in lines if x.get("kind") == "reserved"]
    assert reserved, "expected the call to reserve"
    tok = reserved[-1]["token"]
    actuals = [x for x in lines if x.get("token") == tok and x.get("kind") == "actual"]
    assert actuals, "the real cost must be reconciled once the paid call returns"
    assert actuals[-1].get("amount") == 0.20, (
        "a post-call IO failure must record the REAL billed cost, not release the reserve to 0"
    )
