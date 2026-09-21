"""Frozen contract — increment 0: a FAILED `agents.llm` call must RELEASE its budget reserve.

`agents._post_chat_completion` RESERVES a conservative estimate before the paid OpenRouter call
and, on success, reconciles the real cost. But on a 402 (insufficient credits), a generic non-2xx,
or retries-exhausted (429), the reserve was never released — and because a token's effective spend
falls back to its RESERVED amount when no "actual" was recorded
(sfvf._budget._TokenState.effective_amount), the phantom reserve keeps counting toward the per-day
ceiling. `check_relevance`/`source(consider=N)` fan out to up to N vision calls each, so a run of
failures would accumulate phantom spend and can block legitimate runs. This is the agents.llm
analogue of the media-layer fix (H52, test_budget_release.py): the reserve must be reconciled to
0.0 ("released") on every non-success exit, scoped to the paid call only.

No live network: the adapter's HTTP client is a MockTransport; only the budget ledger (tmp) is used.
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
_KEY = "sk-fake-inmemory-not-real"


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += max(0.0, seconds)


def _ctx(tmp: Path) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=False,
            secrets={"OPENROUTER_API_KEY": _KEY},
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
            budget=BudgetConfig(
                ledger_path=tmp / "budget" / "ledger.jsonl",
                per_day={"openrouter": 100.0},
                estimates={"openrouter": 0.01},  # a non-zero reserve, so a leak is observable
            ),
        )
    )


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler, *, clock: _FakeClock | None = None):
    def wrapped(request: httpx2.Request) -> httpx2.Response:
        return handler(request)

    def _client() -> httpx2.Client:
        return httpx2.Client(base_url=_BASE, transport=httpx2.MockTransport(wrapped))

    monkeypatch.setattr(agents, "_http_client", _client)
    if clock is not None:
        monkeypatch.setattr(
            agents, "_LIMITER", RateLimiter(monotonic=clock.monotonic, sleep=clock.sleep)
        )


def _run(ctx: Context, fn):
    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def _ledger(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _assert_released(ledger_path: Path) -> None:
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
        "a failed agents.llm call must RELEASE its reserve (reconcile to 0), not leak to per_day"
    )


def _402(_request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(402, json={"error": {"code": 402, "message": "Insufficient"}})


def _500(_request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(500, json={"error": {"code": 500, "message": "boom"}})


def test_402_releases_the_reserve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx(tmp_path)
    _install_mock(monkeypatch, _402)
    with pytest.raises(RuntimeError):
        _run(ctx, lambda: agents.llm("q", agent="w", model="m"))
    _assert_released(tmp_path / "budget" / "ledger.jsonl")


def test_generic_non_2xx_releases_the_reserve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path)
    _install_mock(monkeypatch, _500)
    with pytest.raises(RuntimeError):
        _run(ctx, lambda: agents.llm("q", agent="w", model="m"))
    _assert_released(tmp_path / "budget" / "ledger.jsonl")


def test_retries_exhausted_429_releases_the_reserve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def always_429(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429, headers={"Retry-After": "1"}, json={"error": {"code": 429}})

    clock = _FakeClock()
    ctx = _ctx(tmp_path)
    _install_mock(monkeypatch, always_429, clock=clock)
    with pytest.raises(RuntimeError):
        _run(ctx, lambda: agents.llm("q", agent="w", model="m"))
    _assert_released(tmp_path / "budget" / "ledger.jsonl")


def test_success_reconciles_the_real_cost_not_a_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reserved region must cover only the paid call: on SUCCESS the real usage.cost is
    # reconciled (not released to 0), so a genuine spend still counts toward the ceiling.
    def ok(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, json={"choices": [{"message": {"content": "hi"}}], "usage": {"cost": 0.02}}
        )

    ctx = _ctx(tmp_path)
    _install_mock(monkeypatch, ok)
    out = _run(ctx, lambda: agents.llm("q", agent="w", model="m"))
    assert out == "hi"
    lines = _ledger(tmp_path / "budget" / "ledger.jsonl")
    reserved = [x for x in lines if x.get("kind") == "reserved"]
    assert reserved
    tok = reserved[-1]["token"]
    actuals = [x for x in lines if x.get("token") == tok and x.get("kind") == "actual"]
    assert actuals and actuals[-1].get("amount") == pytest.approx(0.02), (
        "a successful call must reconcile the REAL billed cost, not release to 0"
    )
