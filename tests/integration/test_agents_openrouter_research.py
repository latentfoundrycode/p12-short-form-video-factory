"""B-4d contract: real `agents.research` over OpenRouter web search, MOCKED HTTP only.

`research(query) -> list[Source]` has no model argument, so the adapter uses a pinned default
model with OpenRouter's **web plugin** (`plugins:[{"id":"web"}]`). Web results come back as
message **annotations** (`url_citation` objects with `url`/`title`/`content`), which the adapter
maps to `Source{title, url, snippet}`. It reuses B-4c's HTTP plumbing (the `_http_client` seam,
the `_LIMITER`, `ctx.secret`, and the shared retry/error handling), exercised here entirely
against `httpx2.MockTransport` — no live network call. `dry_run` stays the deterministic stub.
"""

import json
from pathlib import Path

import httpx2
import pytest
from sfvf import Source, agents
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths

_BASE = "https://openrouter.ai/api/v1"
_KEY = "sk-fake-inmemory-not-real"


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


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx2.Request]:
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request, len(seen))

    def _client() -> httpx2.Client:
        return httpx2.Client(base_url=_BASE, transport=httpx2.MockTransport(wrapped))

    monkeypatch.setattr(agents, "_http_client", _client)
    return seen


def _run(ctx: Context, fn):
    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def _annotated(*citations: dict[str, str]) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": "summary",
                    "annotations": [{"type": "url_citation", "url_citation": c} for c in citations],
                }
            }
        ],
        "usage": {},
    }


def test_research_dry_run_makes_no_call_and_returns_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_request: httpx2.Request, _n: int) -> httpx2.Response:
        raise AssertionError("dry_run research must not make any network call")

    seen = _install_mock(monkeypatch, boom)
    ctx = _ctx(tmp_path, dry_run=True)
    out = _run(ctx, lambda: agents.research("fusion"))
    assert isinstance(out, list)
    assert out and all("title" in s and "url" in s and "snippet" in s for s in out)
    assert seen == []


def test_research_real_maps_url_citations_to_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(
            200,
            json=_annotated(
                {"url": "https://a.example/1", "title": "First", "content": "snippet one"},
                {"url": "https://b.example/2", "title": "Second", "content": "snippet two"},
            ),
        )

    seen = _install_mock(monkeypatch, handler)
    ctx = _ctx(tmp_path, dry_run=False)
    out: list[Source] = _run(ctx, lambda: agents.research("fusion"))

    assert [s["url"] for s in out] == ["https://a.example/1", "https://b.example/2"]
    assert out[0]["title"] == "First"
    assert out[0]["snippet"] == "snippet one"

    # The request carried auth, a pinned model, and the web plugin.
    req = seen[0]
    assert req.headers.get("authorization") == f"Bearer {_KEY}"
    body = json.loads(req.read())
    assert isinstance(body.get("model"), str) and body["model"]
    assert any(p.get("id") == "web" for p in body.get("plugins", []))
    assert body["messages"][-1]["content"] == "fusion"


def test_research_real_no_annotations_returns_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(
            200, json={"choices": [{"message": {"content": "nothing"}}], "usage": {}}
        )

    _install_mock(monkeypatch, handler)
    ctx = _ctx(tmp_path, dry_run=False)
    out = _run(ctx, lambda: agents.research("obscure"))
    assert out == []


def test_research_real_missing_key_raises_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_request: httpx2.Request, _n: int) -> httpx2.Response:
        raise AssertionError("must fail on the missing key before any network call")

    seen = _install_mock(monkeypatch, boom)
    ctx = _ctx(tmp_path, dry_run=False, secrets={})
    with pytest.raises(KeyError):
        _run(ctx, lambda: agents.research("q"))
    assert seen == []


def test_research_requires_active_context() -> None:
    with pytest.raises(RuntimeError):
        agents.research("q")
