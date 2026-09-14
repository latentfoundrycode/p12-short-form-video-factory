"""G-7b contract: the REAL OpenRouter completion for learning, over MOCKED HTTP only (§5.11).

No network call is ever made — the completion's `httpx2` client is built through an injected
`client_factory` that these tests replace with an `httpx2.MockTransport` standing in for
https://openrouter.ai/api/v1/chat/completions. Spend is gated by a SEPARATE `learning` budget meter
(distinct from the `openrouter` generation meter — PRD: improving a workflow must never eat the
video budget) via the SDK `BudgetGuard` money-engine, and the actual `usage.cost` is reconciled into
the ledger. `make_openrouter_completion(...)` returns a `CompleteFn` that drops straight into
`make_optimizer(complete)` (G-7a). Fail-closed: no budget / kill-switch / missing key ⇒ no call.
The FIRST real run (a live key + a live call) remains the attended money-gate; nothing here spends.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx2
import pytest
from sfvf._budget import BudgetError
from sfvf.context import BudgetConfig

from app.learning.completion import (
    LEARNING_METER,
    CompletionError,
    make_openrouter_completion,
)

_BASE = "https://openrouter.ai/api/v1"
_KEY = "sk-fake-inmemory-not-real"
_MSGS = [{"role": "system", "content": "opt"}, {"role": "user", "content": "improve"}]

Handler = Callable[[httpx2.Request, int], httpx2.Response]


def _budget(
    tmp: Path, *, estimate: float = 0.01, per_day: float | None = None, kill: bool = False
) -> BudgetConfig:
    state = tmp / "budget"
    state.mkdir(parents=True, exist_ok=True)
    kill_switch = state / "STOP"
    if kill:
        kill_switch.write_text("stop", encoding="utf-8")
    return BudgetConfig(
        ledger_path=state / "ledger.jsonl",
        kill_switch_path=kill_switch,
        per_run={},
        per_day={} if per_day is None else {LEARNING_METER: per_day},
        estimates={LEARNING_METER: estimate},
    )


def _factory(
    handler: Handler,
) -> tuple[Callable[[], httpx2.Client], list[httpx2.Request], list[int]]:
    """A client_factory routed through MockTransport; records requests and factory invocations."""
    seen: list[httpx2.Request] = []
    calls: list[int] = []

    def make() -> httpx2.Client:
        calls.append(1)

        def wrapped(request: httpx2.Request) -> httpx2.Response:
            seen.append(request)
            return handler(request, len(seen))

        return httpx2.Client(base_url=_BASE, transport=httpx2.MockTransport(wrapped))

    return make, seen, calls


def _ok(content: str = '{"edits": []}', cost: float = 0.004) -> Handler:
    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={"choices": [{"message": {"content": content}}], "usage": {"cost": cost}},
        )

    return handler


def test_returns_content_and_sends_auth_model_messages(tmp_path: Path) -> None:
    factory, seen, _ = _factory(_ok(content='{"edits": []}'))
    complete = make_openrouter_completion(
        secrets={"OPENROUTER_API_KEY": _KEY},
        budget=_budget(tmp_path),
        model="anthropic/claude-x",
        run_id="learn-1",
        client_factory=factory,
    )
    out = complete(_MSGS)
    assert out == '{"edits": []}'
    assert len(seen) == 1
    req = seen[0]
    assert req.headers.get("authorization") == f"Bearer {_KEY}"
    assert str(req.url).endswith("/chat/completions")
    body = json.loads(req.read())
    assert body["model"] == "anthropic/claude-x"
    assert body["messages"] == _MSGS


def test_meters_actual_cost_into_learning_meter(tmp_path: Path) -> None:
    budget = _budget(tmp_path, estimate=0.01)
    factory, _, _ = _factory(_ok(cost=0.037))
    complete = make_openrouter_completion(
        secrets={"OPENROUTER_API_KEY": _KEY},
        budget=budget,
        model="m",
        run_id="learn-1",
        client_factory=factory,
    )
    complete(_MSGS)
    lines = [
        json.loads(line)
        for line in budget.ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    learning = [entry for entry in lines if entry.get("meter") == LEARNING_METER]
    assert learning  # the learning meter was used (not the generation meter)
    # the actual usage.cost (not just the estimate) was reconciled into the ledger
    assert any(abs(float(entry["amount"]) - 0.037) < 1e-9 for entry in learning)


def test_fail_closed_without_budget(tmp_path: Path) -> None:
    factory, seen, calls = _factory(_ok())
    complete = make_openrouter_completion(
        secrets={"OPENROUTER_API_KEY": _KEY},
        budget=None,
        model="m",
        run_id="r",
        client_factory=factory,
    )
    with pytest.raises(BudgetError):
        complete(_MSGS)
    assert calls == [] and seen == []  # refused before any HTTP client was built


def test_kill_switch_blocks_the_call(tmp_path: Path) -> None:
    factory, seen, calls = _factory(_ok())
    complete = make_openrouter_completion(
        secrets={"OPENROUTER_API_KEY": _KEY},
        budget=_budget(tmp_path, kill=True),
        model="m",
        run_id="r",
        client_factory=factory,
    )
    with pytest.raises(BudgetError):  # KillSwitchEngagedError is a BudgetError
        complete(_MSGS)
    assert calls == [] and seen == []


def test_missing_api_key_raises_before_any_call(tmp_path: Path) -> None:
    factory, seen, calls = _factory(_ok())
    complete = make_openrouter_completion(
        secrets={},
        budget=_budget(tmp_path),
        model="m",
        run_id="r",
        client_factory=factory,
    )
    with pytest.raises(CompletionError):
        complete(_MSGS)
    assert calls == [] and seen == []  # refused before reserving or building a client


def test_non_200_raises_completion_error(tmp_path: Path) -> None:
    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(402, json={"error": "insufficient credits"})

    factory, seen, _ = _factory(handler)
    complete = make_openrouter_completion(
        secrets={"OPENROUTER_API_KEY": _KEY},
        budget=_budget(tmp_path),
        model="m",
        run_id="r",
        client_factory=factory,
    )
    with pytest.raises(CompletionError):
        complete(_MSGS)
    assert len(seen) == 1  # it did attempt the call


def test_missing_content_raises_completion_error(tmp_path: Path) -> None:
    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(200, json={"choices": [{"message": {}}], "usage": {"cost": 0.0}})

    factory, seen, _ = _factory(handler)
    complete = make_openrouter_completion(
        secrets={"OPENROUTER_API_KEY": _KEY},
        budget=_budget(tmp_path),
        model="m",
        run_id="r",
        client_factory=factory,
    )
    with pytest.raises(CompletionError):
        complete(_MSGS)
