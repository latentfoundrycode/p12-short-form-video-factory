"""Frozen contract — Stage P, P-4: the media.video router + the BytePlus Seedance adapter.

media.video.generate becomes a registry router: a legacy Higgsfield slug still runs the inline
Higgsfield path (test_video_higgsfield.py stays green, unchanged), while a registered video model
is dispatched to its adapter. The first video adapter is BytePlus ModelArk Seedance — ASYNCHRONOUS:
POST /contents/generations/tasks (a `content` array of text + image_url items; image_url items carry
an optional role of first_frame/last_frame) -> {id}; poll GET /contents/generations/tasks/{id} until
status "succeeded"; download the MP4 at content.video_url. Cost is METERED: usage.total_tokens / 1e6
x the model's pinned $/1M-tokens (source "metered").

Reference/frame images cross to the provider as URLs. The local-file -> URL bridge is settled in
SFVF CORE (a shared helper, not per workflow): an already-http(s) value passes through; a local
video-relative path is read and inlined as a `data:<mime>;base64,...` URL (option 1, which BytePlus
accepts). The upload/asset-id path (option 2) is the documented fallback, not needed here.

HTTP is exercised against httpx2.MockTransport by monkeypatching `sfvf.providers.byteplus._client`
(+ `_POLL_INTERVAL_S` so polling does not sleep). No live network, an in-memory fake key.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx2
import pytest
from sfvf import media
from sfvf.context import BudgetConfig, Context, ContextFile, ContextPaths
from sfvf.providers import CapabilityError, capabilities_offered, resolve

_KEY = "ark-fake-key-not-real"
_MODEL = "byteplus/seedance-2.5"
_SLUG = "dreamina-seedance-2-5-260628"
_MP4 = b"\x00\x00\x00\x18ftypmp42FAKE-SEEDANCE-VIDEO"
_VIDEO_URL = "https://cdn.example.test/generated/vid.mp4"
_TOTAL_TOKENS = 100_000  # metered cost = 100000/1e6 * price


def _ctx(tmp: Path, *, dry_run: bool, secrets: dict[str, object] | None = None) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            secrets={"BYTEPLUS_ARK_API_KEY": _KEY} if secrets is None else secrets,
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
            budget=BudgetConfig(
                ledger_path=tmp / "budget" / "ledger.jsonl",
                per_day={"byteplus": 1_000_000.0},
                estimates={},
            ),
        )
    )


def _completed_handler(polls_before_done: int = 1):
    """submit -> {id}; status running N times then succeeded (+usage); video_url -> bytes."""

    def handler(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/contents/generations/tasks"):
            return httpx2.Response(200, json={"id": "cgt-123"})
        if request.method == "GET" and "/contents/generations/tasks/" in path:
            n = sum(
                1
                for r in seen
                if r.method == "GET" and "/contents/generations/tasks/" in r.url.path
            )
            if n <= polls_before_done:
                return httpx2.Response(200, json={"id": "cgt-123", "status": "running"})
            return httpx2.Response(
                200,
                json={
                    "id": "cgt-123",
                    "status": "succeeded",
                    "content": {"video_url": _VIDEO_URL},
                    "usage": {"completion_tokens": _TOTAL_TOKENS, "total_tokens": _TOTAL_TOKENS},
                    "resolution": "720p",
                    "duration": 5,
                },
            )
        if request.method == "GET" and path == "/generated/vid.mp4":
            return httpx2.Response(200, content=_MP4)
        raise AssertionError(f"unexpected request: {request.method} {path}")

    return handler


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx2.Request]:
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request, seen)

    def _client(base_url: str) -> httpx2.Client:
        return httpx2.Client(base_url=base_url, transport=httpx2.MockTransport(wrapped))

    from sfvf.providers import byteplus as byteplus_adapter

    monkeypatch.setattr(byteplus_adapter, "_client", _client)
    monkeypatch.setattr(byteplus_adapter, "_POLL_INTERVAL_S", 0.0)
    return seen


def _run(ctx: Context, fn):
    from sfvf._runtime import reset_active, set_active

    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def _submit_body(seen: list[httpx2.Request]) -> dict:
    submit = next(r for r in seen if r.method == "POST")
    return json.loads(submit.read())


def _cost_events(captured: str) -> list[dict]:
    events = []
    for line in captured.splitlines():
        s = line.strip()
        if s.startswith("{"):
            try:
                obj = json.loads(s)
            except ValueError:
                continue
            if obj.get("t") == "cost":
                events.append(obj)
    return events


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_seedance_model_registered_with_video_capabilities() -> None:
    provider, model = resolve(_MODEL)
    assert provider.id == "byteplus" and model.kind == "video"
    assert model.slug == _SLUG
    assert {"video.generate", "video.refs", "video.first_frame"} <= model.capabilities
    assert "video.generate" in capabilities_offered({"BYTEPLUS_ARK_API_KEY"})
    assert "video.generate" not in capabilities_offered(set())


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_generate_dry_run_makes_no_call_and_returns_a_stub_clip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_request: httpx2.Request, _seen: list[httpx2.Request]) -> httpx2.Response:
        raise AssertionError("dry_run video generation must not make any network call")

    seen = _install_mock(monkeypatch, boom)
    ctx = _ctx(tmp_path, dry_run=True)
    out = _run(ctx, lambda: media.video.generate("a fox", model=_MODEL, duration_s=2.0))

    clip = tmp_path / out
    assert clip.is_file()
    assert seen == []


# ---------------------------------------------------------------------------
# Real text-to-video — submit / poll / download / metered cost
# ---------------------------------------------------------------------------


def test_generate_real_submits_polls_downloads_and_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _completed_handler(polls_before_done=1))
    ctx = _ctx(tmp_path, dry_run=False)
    out = _run(
        ctx,
        lambda: media.video.generate(
            "a fox", model=_MODEL, duration_s=5.0, extra={"ratio": "9:16"}
        ),
    )
    clip = tmp_path / out
    assert clip.read_bytes() == _MP4

    submit = next(r for r in seen if r.method == "POST")
    assert submit.url.path.endswith("/contents/generations/tasks")
    assert submit.headers.get("authorization") == f"Bearer {_KEY}"
    body = _submit_body(seen)
    assert body["model"] == _SLUG
    assert body["content"][0] == {"type": "text", "text": "a fox"}
    assert body.get("duration") == 5
    assert body.get("ratio") == "9:16"  # passthrough via extra
    # it polled the task endpoint then fetched the video
    assert sum(1 for r in seen if r.method == "GET" and "/tasks/" in r.url.path) >= 2
    assert any(r.method == "GET" and r.url.path == "/generated/vid.mp4" for r in seen)


def test_generate_real_records_a_metered_cost_from_token_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    _run(ctx, lambda: media.video.generate("a fox", model=_MODEL, duration_s=5.0))

    _, model = resolve(_MODEL)
    expected = _TOTAL_TOKENS / 1_000_000 * model.price.amount
    events = _cost_events(capsys.readouterr().out)
    assert events
    event = events[-1]
    assert event["meter"] == "byteplus" and event["unit"] == "usd"
    assert event["source"] == "metered"
    assert event["amount"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Reference / frame images -> URLs (the core local-file -> data-URI bridge)
# ---------------------------------------------------------------------------


def test_first_and_last_frame_local_files_become_data_uri_content_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "artifacts" / "a.png").write_bytes(b"\x89PNG\r\n\x1a\nAAA")
    (tmp_path / "artifacts" / "b.png").write_bytes(b"\x89PNG\r\n\x1a\nBBB")

    _run(
        ctx,
        lambda: media.video.generate(
            "a fox",
            model=_MODEL,
            first_frame="artifacts/a.png",
            last_frame="artifacts/b.png",
            duration_s=5.0,
        ),
    )
    items = _submit_body(seen)["content"]
    by_role = {it.get("role"): it for it in items if it["type"] == "image_url"}
    assert by_role["first_frame"]["image_url"]["url"].startswith("data:image/png;base64,")
    assert by_role["last_frame"]["image_url"]["url"].startswith("data:image/png;base64,")


def test_ref_that_is_already_a_url_passes_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    _run(
        ctx,
        lambda: media.video.generate(
            "a fox",
            model=_MODEL,
            refs=[{"kind": "character", "path": "https://cdn.example.test/sheet.png"}],
            duration_s=5.0,
        ),
    )
    urls = [
        it["image_url"]["url"] for it in _submit_body(seen)["content"] if it["type"] == "image_url"
    ]
    assert "https://cdn.example.test/sheet.png" in urls  # http(s) passes through, not re-encoded


# ---------------------------------------------------------------------------
# Refusals — before any spend
# ---------------------------------------------------------------------------


def test_refs_on_a_model_without_the_capability_raise_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sfvf.providers import registry
    from sfvf.providers.registry import Model, PriceHint

    monkeypatch.setitem(
        registry.MODELS,
        "byteplus/no-refs",
        Model(
            id="byteplus/no-refs",
            provider="byteplus",
            slug="no-refs",
            kind="video",
            capabilities=frozenset({"video.generate"}),  # no video.refs
            label="No Refs",
            price=PriceHint("usd", "per_1m_tokens", 1.0, "test"),
        ),
    )
    seen = _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    with pytest.raises(CapabilityError):
        _run(
            ctx,
            lambda: media.video.generate(
                "x",
                model="byteplus/no-refs",
                refs=[{"kind": "character", "path": "https://x.test/s.png"}],
            ),
        )
    assert seen == []


def test_generate_missing_key_raises_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False, secrets={})
    with pytest.raises(KeyError):
        _run(ctx, lambda: media.video.generate("x", model=_MODEL, duration_s=5.0))
    assert seen == []


def test_generate_requires_an_active_context() -> None:
    with pytest.raises(RuntimeError):
        media.video.generate("x", model=_MODEL, duration_s=5.0)
