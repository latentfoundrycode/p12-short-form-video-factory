"""C-1 contract: priced calls emit a `cost` event so spend is metered, not just logged (closes H10).

The budget ledger already reserves/reconciles money for the GATE; C-1 adds the user-facing COST
surface. Each real (non-dry) priced provider call emits a `cost` event carrying the meter, the unit,
the amount, and whether the step was a cache hit (by analogy with the §5.4a `forecast` event):

    {"t":"cost","meter":"openrouter","unit":"usd","amount":0.03,"cached":false}

OpenRouter carries its real `usage.cost` (usd). The event is emitted independent of the budget gate
(cost is surfaced whether or not a budget is configured) and only when a usable cost is known — a
missing/malformed `usage.cost` emits no event rather than a bogus zero. `dry_run` is free and emits
none. Mocked HTTP only; no network, no spend. (Higgsfield has no per-call cost from its API — H20 —
so its per-video cost surfacing is a separate follow-up, not part of this increment.)
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx2
import pytest
from sfvf import agents
from sfvf._ratelimit import RateLimiter
from sfvf._runtime import reset_active, set_active
from sfvf.context import BudgetConfig, Context, ContextFile, ContextPaths

_BASE = "https://openrouter.ai/api/v1"
_KEY = "sk-fake-not-real"


def _ctx(tmp: Path, *, dry_run: bool) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            secrets={"OPENROUTER_API_KEY": _KEY},
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
            budget=BudgetConfig(
                ledger_path=tmp / "budget" / "ledger.jsonl",
                per_day={"openrouter": 1_000_000.0},
                estimates={"openrouter": 0.01},
            ),
        )
    )


def _install(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    def _client() -> httpx2.Client:
        return httpx2.Client(base_url=_BASE, transport=httpx2.MockTransport(handler))

    monkeypatch.setattr(agents, "_http_client", _client)
    monkeypatch.setattr(agents, "_LIMITER", RateLimiter())


def _cost_events(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    events: list[dict] = []
    for line in capsys.readouterr().out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("t") == "cost":
            events.append(e)
    return events


def _ok(cost: float | None):
    def handler(request: httpx2.Request) -> httpx2.Response:
        message: dict = {"content": "hi", "annotations": []}
        body: dict = {"choices": [{"message": message}]}
        if cost is not None:
            body["usage"] = {"cost": cost}
        return httpx2.Response(200, json=body)

    return handler


def test_llm_emits_cost_event_with_real_usage_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(monkeypatch, _ok(0.03))
    token = set_active(_ctx(tmp_path, dry_run=False))
    try:
        agents.llm("hi", agent="a", model="m")
    finally:
        reset_active(token)
    costs = _cost_events(capsys)
    assert len(costs) == 1
    c = costs[0]
    assert c["meter"] == "openrouter"
    assert c["unit"] == "usd"
    assert c["amount"] == pytest.approx(0.03)
    assert c["cached"] is False


def test_research_emits_cost_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(monkeypatch, _ok(0.017))
    token = set_active(_ctx(tmp_path, dry_run=False))
    try:
        agents.research("hi")
    finally:
        reset_active(token)
    costs = _cost_events(capsys)
    assert costs and costs[0]["meter"] == "openrouter"
    assert costs[0]["unit"] == "usd"
    assert costs[0]["amount"] == pytest.approx(0.017)
    assert costs[0]["cached"] is False


def test_unusable_cost_emits_no_cost_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A 200 whose usage.cost is missing/malformed must not emit a bogus zero-cost event.
    _install(monkeypatch, _ok(None))
    token = set_active(_ctx(tmp_path, dry_run=False))
    try:
        agents.llm("hi", agent="a", model="m")
    finally:
        reset_active(token)
    assert _cost_events(capsys) == []


def test_dry_run_emits_no_cost_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # dry_run is free and makes no network call — it emits no cost event.
    def boom(request: httpx2.Request) -> httpx2.Response:  # pragma: no cover - must not run
        raise AssertionError("dry_run must not make a network call")

    _install(monkeypatch, boom)
    token = set_active(_ctx(tmp_path, dry_run=True))
    try:
        agents.llm("hi", agent="a", model="m")
    finally:
        reset_active(token)
    assert _cost_events(capsys) == []
