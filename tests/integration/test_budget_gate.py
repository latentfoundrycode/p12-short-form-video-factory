"""T2b-1 contract: the budget guard GATES the real paid-call paths (SDK side).

Wires the T2a `sfvf._budget.BudgetGuard` into the two paid providers so a run cannot spend past its
ceilings or a kill-switch. The gate lives in the SDK because that is where the calls happen:
- OpenRouter (`agents.llm` / `agents.research`, via `_post_chat_completion`) — meter "openrouter".
- media.video providers (e.g. BytePlus/Seedance, via the registry router) — the provider's meter.

Before each real call the SDK RESERVES a conservative per-meter estimate; if the reservation is
refused (ceiling or kill-switch), the call is blocked and NO HTTP request is made. After a
successful OpenRouter call the SDK RECONCILES with the real `usage.cost`. Budget config travels in
`context.json` (`ContextFile.budget`); when it is absent, a real paid call is now REFUSED before any
HTTP (H21 fail-closed) so an unconfigured real run never spends ungated (dry_run never reaches the
paid path). No network call is ever made: HTTP is a MockTransport; a blocked call's transport must
never be invoked. Fake keys/ceilings live only under tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx2
import pytest
from sfvf import (
    agents,
    media,  # noqa: F401  (ensures sfvf.media.video is importable)
)
from sfvf._budget import BudgetError, BudgetExceededError, KillSwitchEngagedError
from sfvf._ratelimit import RateLimiter
from sfvf._runtime import reset_active, set_active
from sfvf.context import BudgetConfig, Context, ContextFile, ContextPaths
from sfvf.media import video

_OR_BASE = "https://openrouter.ai/api/v1"
_OR_KEY = "sk-fake-inmemory-not-real"


def _ledger_lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _budget(
    tmp: Path,
    *,
    per_run: dict[str, float] | None = None,
    per_day: dict[str, float] | None = None,
    estimates: dict[str, float] | None = None,
    kill_switch: Path | None = None,
) -> BudgetConfig:
    return BudgetConfig(
        ledger_path=tmp / "budget" / "ledger.jsonl",
        kill_switch_path=kill_switch,
        per_run=per_run or {},
        per_day=per_day or {},
        estimates=estimates or {},
    )


def _ctx(
    tmp: Path, *, budget: BudgetConfig | None, secrets: dict[str, object] | None = None
) -> Context:
    return Context(
        ContextFile(
            settings={},
            run_id="run-1",
            dry_run=False,
            secrets=secrets if secrets is not None else {"OPENROUTER_API_KEY": _OR_KEY},
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
            budget=budget,
        )
    )


class _NoCallTransport(httpx2.MockTransport):
    """Fails the test if any HTTP request is attempted — proves a blocked call makes no request."""

    def __init__(self) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:  # pragma: no cover - must not run
            raise AssertionError(f"blocked call still hit the network: {request.url}")

        super().__init__(handler)


def _install_or_mock(monkeypatch: pytest.MonkeyPatch, transport: httpx2.MockTransport) -> None:
    monkeypatch.setattr(
        agents, "_http_client", lambda: httpx2.Client(base_url=_OR_BASE, transport=transport)
    )
    monkeypatch.setattr(agents, "_LIMITER", RateLimiter())


def _or_success(cost: float) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"cost": cost},
            },
        )

    return httpx2.MockTransport(handler)


def _or_body(body: dict[str, object]) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=body)

    return httpx2.MockTransport(handler)


# --- OpenRouter gate ---


def test_llm_blocked_when_budget_exhausted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # estimate (0.01) exceeds the per-day ceiling (0.001) → reservation refused → no HTTP call.
    budget = _budget(tmp_path, per_day={"openrouter": 0.001}, estimates={"openrouter": 0.01})
    _install_or_mock(monkeypatch, _NoCallTransport())
    ctx = _ctx(tmp_path, budget=budget)
    token = set_active(ctx)
    try:
        with pytest.raises(BudgetExceededError):
            agents.llm("hi", agent="a", model="m")
    finally:
        reset_active(token)
    # nothing was reserved on a refusal
    assert _ledger_lines(budget.ledger_path) == []


def test_llm_allowed_reserves_then_reconciles_actual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    budget = _budget(tmp_path, per_day={"openrouter": 10.0}, estimates={"openrouter": 0.5})
    _install_or_mock(monkeypatch, _or_success(0.03))
    ctx = _ctx(tmp_path, budget=budget)
    token = set_active(ctx)
    try:
        out = agents.llm("hi", agent="a", model="m")
    finally:
        reset_active(token)
    assert out == "hello"
    entries = _ledger_lines(budget.ledger_path)
    kinds = [e["kind"] for e in entries]
    assert "reserved" in kinds and "actual" in kinds
    actual = next(e for e in entries if e["kind"] == "actual")
    assert actual["meter"] == "openrouter"
    assert actual["amount"] == pytest.approx(0.03)  # reconciled to the real usage.cost


@pytest.mark.parametrize(
    "body",
    [
        {"choices": [{"message": {"content": "hello"}}]},  # no usage key at all
        {"choices": [{"message": {"content": "hello"}}], "usage": None},  # usage present but null
        {"choices": [{"message": {"content": "hello"}}], "usage": []},  # usage a non-dict
        {
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"cost": "oops"},
        },  # cost not a number
    ],
)
def test_llm_success_with_unusable_cost_holds_reservation_without_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: dict[str, object]
):
    # A 200 whose usage/cost is missing or malformed must NOT crash the call AFTER the paid request
    # succeeded — reconcile is skipped and the conservative estimate reservation stands.
    budget = _budget(tmp_path, per_day={"openrouter": 10.0}, estimates={"openrouter": 0.5})
    _install_or_mock(monkeypatch, _or_body(body))
    ctx = _ctx(tmp_path, budget=budget)
    token = set_active(ctx)
    try:
        out = agents.llm("hi", agent="a", model="m")  # must not raise
    finally:
        reset_active(token)
    assert out == "hello"
    entries = _ledger_lines(budget.ledger_path)
    assert [e["kind"] for e in entries] == ["reserved"]  # reservation stands, no actual booked
    assert entries[0]["amount"] == pytest.approx(0.5)


def test_kill_switch_blocks_llm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ks = tmp_path / "STOP"
    ks.write_text("halt", encoding="utf-8")
    budget = _budget(
        tmp_path, per_day={"openrouter": 100.0}, estimates={"openrouter": 0.1}, kill_switch=ks
    )
    _install_or_mock(monkeypatch, _NoCallTransport())
    ctx = _ctx(tmp_path, budget=budget)
    token = set_active(ctx)
    try:
        with pytest.raises(KillSwitchEngagedError):
            agents.llm("hi", agent="a", model="m")
    finally:
        reset_active(token)


def test_no_budget_config_refuses_the_paid_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # H21: a real paid call with NO budget config is refused (fail-closed) BEFORE any HTTP. A real
    # run that reaches a paid provider with no breaker configured must never spend ungated; the
    # refusal is a BudgetError, which the supervisor maps to the stopped-budget status (T2b-2c).
    _install_or_mock(monkeypatch, _NoCallTransport())
    ctx = _ctx(tmp_path, budget=None)
    token = set_active(ctx)
    try:
        with pytest.raises(BudgetError):
            agents.llm("hi", agent="a", model="m")
    finally:
        reset_active(token)
    # A refused call writes no ledger (nothing was reserved).
    assert not (tmp_path / "budget" / "ledger.jsonl").exists()


def test_configured_meter_without_estimate_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Budget is configured but no estimate is set for the meter being charged: proceeding ungated
    # would defeat the guard, so the call must be refused (fail closed), never reserve 0 as unknown.
    budget = _budget(tmp_path, per_day={"openrouter": 10.0}, estimates={})  # no openrouter est.
    _install_or_mock(monkeypatch, _NoCallTransport())
    ctx = _ctx(tmp_path, budget=budget)
    token = set_active(ctx)
    try:
        with pytest.raises(BudgetError):
            agents.llm("hi", agent="a", model="m")
    finally:
        reset_active(token)


# --- Video budget gate ---


def test_video_blocked_when_budget_exhausted(tmp_path: Path):
    # A registered video model whose per-call estimate exceeds a tiny per-day ceiling is refused at
    # the reserve — before the adapter makes any HTTP call — so the ledger stays empty.
    budget = _budget(tmp_path, per_day={"byteplus": 0.0001}, estimates={})
    ctx = _ctx(tmp_path, budget=budget, secrets={"BYTEPLUS_ARK_API_KEY": "ark-fake-not-real"})
    token = set_active(ctx)
    try:
        with pytest.raises(BudgetExceededError):
            video.generate("a cat", model="byteplus/seedance-2.5", duration_s=4.0)
    finally:
        reset_active(token)
    assert _ledger_lines(budget.ledger_path) == []
