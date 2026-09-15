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


def test_failed_call_releases_its_budget_reservation(tmp_path: Path) -> None:
    # A non-200 failure is not billed, so it must RELEASE its reservation (reconcile to 0) instead
    # of leaving the estimate standing — else repeated failures accumulate and exhaust the budget.
    # With per_day just above one estimate, a second failing call would be blocked at reserve if the
    # first's reservation still stood; releasing it lets the second call reach the endpoint again.
    budget = _budget(tmp_path, estimate=0.10, per_day=0.15)

    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(402, json={"error": "insufficient credits"})

    factory, seen, _ = _factory(handler)
    complete = make_openrouter_completion(
        secrets={"OPENROUTER_API_KEY": _KEY},
        budget=budget,
        model="m",
        run_id="r",
        client_factory=factory,
    )
    with pytest.raises(CompletionError):
        complete(_MSGS)  # first 402 — releases its reservation
    with pytest.raises(CompletionError):
        complete(_MSGS)  # second 402, NOT a BudgetError from an accumulated reservation
    assert len(seen) == 2  # both calls reached the endpoint (second not blocked at reserve)


def test_transport_error_keeps_the_reservation(tmp_path: Path) -> None:
    # A transport failure (no HTTP response) is AMBIGUOUS — OpenRouter may have processed and BILLED
    # the request before the connection dropped — so it must NOT release the reservation (that would
    # under-count real spend and let the daily ceiling be exceeded). Only a confirmed-unbilled
    # failure (a non-2xx response / exhausted 429) releases. So a second call is correctly blocked.
    budget = _budget(tmp_path, estimate=0.10, per_day=0.15)

    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        raise RuntimeError("simulated transport failure")

    factory, _, _ = _factory(handler)
    complete = make_openrouter_completion(
        secrets={"OPENROUTER_API_KEY": _KEY},
        budget=budget,
        model="m",
        run_id="r",
        client_factory=factory,
    )
    with pytest.raises(RuntimeError):
        complete(
            _MSGS
        )  # transport error propagates; reservation is NOT released (ambiguous billing)
    with pytest.raises(BudgetError):
        complete(_MSGS)  # second call blocked at reserve — the first reservation still stands


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


# --- H43: untrusted-response error contract + bounded 429/Retry-After retry ---


def test_malformed_body_raises_completion_error(tmp_path: Path) -> None:
    # A 200 whose body is not JSON must surface as CompletionError, never a raw JSONDecodeError.
    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(200, content=b"not json at all")

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
    assert len(seen) == 1


def test_non_dict_json_body_raises_completion_error(tmp_path: Path) -> None:
    # A 200 whose top-level JSON is not an object surfaces as CompletionError, not AttributeError.
    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(200, json=[1, 2, 3])

    factory, _, _ = _factory(handler)
    complete = make_openrouter_completion(
        secrets={"OPENROUTER_API_KEY": _KEY},
        budget=_budget(tmp_path),
        model="m",
        run_id="r",
        client_factory=factory,
    )
    with pytest.raises(CompletionError):
        complete(_MSGS)


def test_retries_on_429_then_succeeds(tmp_path: Path) -> None:
    def handler(_request: httpx2.Request, n: int) -> httpx2.Response:
        if n == 1:
            return httpx2.Response(429, headers={"Retry-After": "5"}, json={"error": 429})
        return httpx2.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}], "usage": {"cost": 0.001}},
        )

    factory, seen, _ = _factory(handler)
    slept: list[float] = []
    complete = make_openrouter_completion(
        secrets={"OPENROUTER_API_KEY": _KEY},
        budget=_budget(tmp_path),
        model="m",
        run_id="r",
        client_factory=factory,
        sleep=slept.append,
    )
    assert complete(_MSGS) == "ok"
    assert len(seen) == 2  # retried after the 429
    assert 5.0 in slept  # honored Retry-After via the injected sleep (no real wait)


def test_429_exhausted_raises_completion_error(tmp_path: Path) -> None:
    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(429, headers={"Retry-After": "1"}, json={"error": 429})

    factory, seen, _ = _factory(handler)
    complete = make_openrouter_completion(
        secrets={"OPENROUTER_API_KEY": _KEY},
        budget=_budget(tmp_path),
        model="m",
        run_id="r",
        client_factory=factory,
        sleep=lambda _seconds: None,
    )
    with pytest.raises(CompletionError):
        complete(_MSGS)
    assert len(seen) >= 2  # bounded retries were attempted, then it gave up


def test_no_sleep_after_the_final_attempt(tmp_path: Path) -> None:
    # A large Retry-After on the LAST 429 must not stall the failure: sleep only between attempts,
    # never after the final one (else an exhausted retry could hang for the Retry-After duration).
    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(429, headers={"Retry-After": "9999"}, json={"error": 429})

    factory, seen, _ = _factory(handler)
    slept: list[float] = []
    complete = make_openrouter_completion(
        secrets={"OPENROUTER_API_KEY": _KEY},
        budget=_budget(tmp_path),
        model="m",
        run_id="r",
        client_factory=factory,
        sleep=slept.append,
    )
    with pytest.raises(CompletionError):
        complete(_MSGS)
    assert len(slept) == len(seen) - 1  # slept between attempts only, never after the last one
