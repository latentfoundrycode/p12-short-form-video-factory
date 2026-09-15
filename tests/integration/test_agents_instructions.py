"""Close the learning loop: agents.llm / agents.research auto-inject the workflow's frozen
instruction files (its rules/ and skills/) into every LLM prompt, so accepted rules actually steer
generation (§5.11). Exercised against MOCKED HTTP only — no network call is made.

Without this, `ctx.instructions` is carried but nothing consumes it, so a workflow's rules never
reach the model and learning is cosmetic. Here the content of every path in `ctx.instructions` is
prepended, in order, as a single leading `system` message ahead of the caller's prompt; an empty
`instructions` injects nothing (backward-compatible with existing callers).
"""

from __future__ import annotations

from pathlib import Path

import httpx2
import pytest
from sfvf import agents
from sfvf._runtime import reset_active, set_active
from sfvf.context import BudgetConfig, Context, ContextFile, ContextPaths

_BASE = "https://openrouter.ai/api/v1"
_KEY = "sk-fake-inmemory-not-real"


def _ctx(tmp: Path, *, instructions: list[Path]) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=False,
            secrets={"OPENROUTER_API_KEY": _KEY},
            instructions=instructions,
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


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx2.Request]:
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request, len(seen))

    def _client() -> httpx2.Client:
        return httpx2.Client(base_url=_BASE, transport=httpx2.MockTransport(wrapped))

    monkeypatch.setattr(agents, "_http_client", _client)
    return seen


def _ok(_request: httpx2.Request, _n: int) -> httpx2.Response:
    return httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})


def _run(ctx: Context, fn):
    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def _rule(tmp: Path, name: str, text: str) -> Path:
    path = tmp / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _messages(seen: list[httpx2.Request]) -> list[dict[str, str]]:
    import json

    return list(json.loads(seen[0].read())["messages"])


def test_instructions_prepended_as_leading_system_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule_a = _rule(tmp_path / "rules", "tone.md", "Open on the strongest concrete visual.")
    rule_b = _rule(tmp_path / "skills", "hooks.md", "State the topic in the first three seconds.")
    seen = _install_mock(monkeypatch, _ok)
    out = _run(
        _ctx(tmp_path, instructions=[rule_a, rule_b]),
        lambda: agents.llm("write the script", agent="script", model="m"),
    )
    assert out == "ok"
    messages = _messages(seen)
    assert messages[0]["role"] == "system"  # instructions lead
    assert "Open on the strongest concrete visual." in messages[0]["content"]
    assert "State the topic in the first three seconds." in messages[0]["content"]  # both, in order
    assert messages[-1] == {"role": "user", "content": "write the script"}  # caller prompt last


def test_no_instructions_injects_no_system_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ok)
    _run(
        _ctx(tmp_path, instructions=[]),
        lambda: agents.llm("write the script", agent="script", model="m"),
    )
    messages = _messages(seen)
    assert messages == [{"role": "user", "content": "write the script"}]  # unchanged, no injection


def test_research_also_receives_the_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule = _rule(tmp_path / "rules", "tone.md", "Prefer concrete, verifiable facts.")
    seen = _install_mock(monkeypatch, _ok)
    _run(_ctx(tmp_path, instructions=[rule]), lambda: agents.research("ocean tides"))
    messages = _messages(seen)
    assert messages[0]["role"] == "system"
    assert "Prefer concrete, verifiable facts." in messages[0]["content"]
