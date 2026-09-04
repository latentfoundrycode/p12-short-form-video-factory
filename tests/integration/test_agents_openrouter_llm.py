"""B-4c contract: real `agents.llm` over OpenRouter, exercised against MOCKED HTTP only.

No network call is ever made: the real path's httpx client is replaced with an
`httpx2.MockTransport` that stands in for `https://openrouter.ai/api/v1/chat/completions`
(auth header, success payload with `usage`, 402/429 + Retry-After). `dry_run` stays a genuine
no-network stub. Per SDK §10 dry_run stubs PAID providers; the real path is what these mocks
drive. Cost is parsed from `usage.cost` and surfaced (a log line), but NO cost event is emitted
— the budget-engine cost/meter schema is Stage C's (see docs/HARDENING.md).

Seams the adapter must expose for this (both patched here, never hitting the network):
  * `agents._http_client() -> httpx2.Client` — the real path builds its client through this.
  * `agents._LIMITER` — the module-level RateLimiter the real path queues behind (patched with a
    fake-clock limiter so a honored Retry-After is asserted without real waiting).
"""

import json
from pathlib import Path

import httpx2
import pytest
from sfvf import agents
from sfvf._ratelimit import RateLimiter
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths

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


def _ctx(tmp: Path, *, dry_run: bool, secrets: dict[str, object] | None = None) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            secrets={"OPENROUTER_API_KEY": _KEY} if secrets is None else secrets,
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
        )
    )


def _install_mock(
    monkeypatch: pytest.MonkeyPatch,
    handler,
    *,
    clock: _FakeClock | None = None,
) -> list[httpx2.Request]:
    """Route the adapter's client through a MockTransport; record requests. No network."""
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request, len(seen))

    def _client() -> httpx2.Client:
        return httpx2.Client(base_url=_BASE, transport=httpx2.MockTransport(wrapped))

    monkeypatch.setattr(agents, "_http_client", _client)
    if clock is not None:
        monkeypatch.setattr(
            agents, "_LIMITER", RateLimiter(monotonic=clock.monotonic, sleep=clock.sleep)
        )
    return seen


def _run(ctx: Context, fn):
    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def test_llm_dry_run_makes_no_network_call_and_returns_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_request: httpx2.Request, _n: int) -> httpx2.Response:
        raise AssertionError("dry_run must not make any network call")

    seen = _install_mock(monkeypatch, boom)
    ctx = _ctx(tmp_path, dry_run=True)
    out = _run(ctx, lambda: agents.llm("hello", agent="writer", model="openai/gpt-4"))
    assert isinstance(out, str)
    assert seen == []  # transport never invoked


def test_llm_real_sends_authorized_request_and_returns_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "id": "x",
                "choices": [{"message": {"role": "assistant", "content": "the answer"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            },
        )

    seen = _install_mock(monkeypatch, handler)
    ctx = _ctx(tmp_path, dry_run=False)
    out = _run(ctx, lambda: agents.llm("q", agent="writer", model="openai/gpt-4"))
    assert out == "the answer"
    assert len(seen) == 1
    req = seen[0]
    assert req.headers.get("authorization") == f"Bearer {_KEY}"
    assert str(req.url).endswith("/chat/completions")
    body = json.loads(req.read())
    assert body["model"] == "openai/gpt-4"
    assert body["messages"][-1]["content"] == "q"


def test_llm_real_schema_returns_parsed_dict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}

    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"title": "Hi"})}}],
                "usage": {"total_tokens": 4},
            },
        )

    seen = _install_mock(monkeypatch, handler)
    ctx = _ctx(tmp_path, dry_run=False)
    out = _run(ctx, lambda: agents.llm("q", agent="w", model="m", schema=schema))
    assert out == {"title": "Hi"}
    body = json.loads(seen[0].read())
    # schema requested structured output
    assert body["response_format"]["type"] == "json_schema"


def test_llm_real_429_honors_retry_after_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(_request: httpx2.Request, n: int) -> httpx2.Response:
        if n == 1:
            return httpx2.Response(
                429, headers={"Retry-After": "30"}, json={"error": {"code": 429}}
            )
        return httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    clock = _FakeClock()
    seen = _install_mock(monkeypatch, handler, clock=clock)
    ctx = _ctx(tmp_path, dry_run=False)
    out = _run(ctx, lambda: agents.llm("q", agent="w", model="m"))
    assert out == "ok"
    assert len(seen) == 2  # retried after the 429
    # The Retry-After of 30s was honored via the limiter's back-off (fake clock, no real wait).
    assert any(abs(s - 30.0) < 0.01 for s in clock.sleeps)


def test_llm_real_nonfinite_retry_after_does_not_hang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A hostile/buggy 'Retry-After: inf' must NOT become an unbounded sleep(inf) that hangs the
    # bounded retry — the adapter rejects non-finite/negative values and uses the finite default.
    def handler(_request: httpx2.Request, n: int) -> httpx2.Response:
        if n == 1:
            return httpx2.Response(
                429, headers={"Retry-After": "inf"}, json={"error": {"code": 429}}
            )
        return httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    clock = _FakeClock()
    _install_mock(monkeypatch, handler, clock=clock)
    ctx = _ctx(tmp_path, dry_run=False)
    out = _run(ctx, lambda: agents.llm("q", agent="w", model="m"))
    assert out == "ok"
    # No infinite back-off was requested; the sleeps that happened are all finite.
    assert all(s != float("inf") for s in clock.sleeps)
    assert all(s < 1_000_000 for s in clock.sleeps)


def test_llm_real_402_raises_without_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(402, json={"error": {"code": 402, "message": "Insufficient"}})

    seen = _install_mock(monkeypatch, handler)
    ctx = _ctx(tmp_path, dry_run=False)
    with pytest.raises(RuntimeError):
        _run(ctx, lambda: agents.llm("q", agent="w", model="m"))
    assert len(seen) == 1  # 402 is terminal, no retry


def test_llm_real_surfaces_cost_without_emitting_cost_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"total_tokens": 8, "cost": 0.0012},
            },
        )

    _install_mock(monkeypatch, handler)
    ctx = _ctx(tmp_path, dry_run=False)
    _run(ctx, lambda: agents.llm("q", agent="w", model="m"))
    events = []
    for line in capsys.readouterr().out.splitlines():
        s = line.strip()
        if s.startswith("{"):
            try:
                events.append(json.loads(s))
            except ValueError:
                continue
    # NO cost event is emitted (Stage C owns the cost/meter schema).
    assert not any(e.get("t") == "cost" for e in events)
    # The real usage.cost IS surfaced somewhere in the event stream (a log line).
    assert any("0.0012" in json.dumps(e) for e in events)


def test_llm_real_missing_key_raises_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_request: httpx2.Request, _n: int) -> httpx2.Response:
        raise AssertionError("must fail on the missing key before any network call")

    seen = _install_mock(monkeypatch, boom)
    ctx = _ctx(tmp_path, dry_run=False, secrets={})
    with pytest.raises(KeyError):
        _run(ctx, lambda: agents.llm("q", agent="w", model="m"))
    assert seen == []


def test_llm_requires_active_context() -> None:
    with pytest.raises(RuntimeError):
        agents.llm("q", agent="w", model="m")
