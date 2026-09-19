"""Frozen contract — Stage P, P-7: the MiniMax (Hailuo H3, v2) video adapter.

MiniMax v2 H3 sits behind the media.video router like Seedance and is structurally the same: async
`POST /v2/video_generation` with a `content` array (text + image_url items carrying a `role` of
first_frame / last_frame / reference_image) and `Authorization: Bearer`; poll
`GET /v2/query/video_generation/{task_id}` (id in the PATH) until `task.status == "succeeded"`; the
finished MP4 is a DIRECT url at `task.content.url` (no file-retrieve step); cost is METERED from the
`task.usage` block (output seconds x the pinned $/second, source "metered"). MiniMax is billed USD
pay-as-you-go, so its meter is fiat/usd.

Reference/frame images cross as URLs via the shared core bridge (local file -> data URI, http(s)
passthrough), exactly as for Seedance. HTTP is exercised against httpx2.MockTransport by
monkeypatching `sfvf.providers.minimax._client` (+ `_POLL_INTERVAL_S`). No live network, fake key.

Note: v2's response nesting is the one shape the docs did not give verbatim; this contract pins the
best-documented reading (`task.status` / `task.content.url` / `task.usage`); confirmed at the smoke.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx2
import pytest
from sfvf import media
from sfvf.context import BudgetConfig, Context, ContextFile, ContextPaths
from sfvf.providers import CapabilityError, capabilities_offered, resolve

_KEY = "mm-fake-key-not-real"
_MODEL = "minimax/hailuo-h3"
_SLUG = "MiniMax-H3"
_MP4 = b"\x00\x00\x00\x18ftypmp42FAKE-MINIMAX-VIDEO"
_VIDEO_URL = "https://cdn.minimax.example.test/out/vid.mp4"
_SECONDS = 4.0


def _ctx(tmp: Path, *, dry_run: bool, secrets: dict[str, object] | None = None) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            secrets={"MINIMAX_API_KEY": _KEY} if secrets is None else secrets,
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
            budget=BudgetConfig(
                ledger_path=tmp / "budget" / "ledger.jsonl",
                per_day={"minimax": 1_000_000.0},
                estimates={},
            ),
        )
    )


def _completed_handler(polls_before_done: int = 1):
    """submit -> {task_id}; query task.status running N times then succeeded; url -> bytes."""

    def handler(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        path = request.url.path
        if request.method == "POST" and path == "/v2/video_generation":
            return httpx2.Response(200, json={"task_id": "mm-123", "base_resp": {"status_code": 0}})
        if request.method == "GET" and path.startswith("/v2/query/video_generation/"):
            n = sum(
                1
                for r in seen
                if r.method == "GET" and r.url.path.startswith("/v2/query/video_generation/")
            )
            if n <= polls_before_done:
                return httpx2.Response(200, json={"task": {"id": "mm-123", "status": "running"}})
            return httpx2.Response(
                200,
                json={
                    "task": {
                        "id": "mm-123",
                        "status": "succeeded",
                        "content": {"url": _VIDEO_URL},
                        "usage": {"total_seconds": _SECONDS, "output_seconds": _SECONDS},
                    },
                    "base_resp": {"status_code": 0},
                },
            )
        if request.method == "GET" and path == "/out/vid.mp4":
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

    from sfvf.providers import minimax as minimax_adapter

    monkeypatch.setattr(minimax_adapter, "_client", _client)
    monkeypatch.setattr(minimax_adapter, "_POLL_INTERVAL_S", 0.0)
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
# Registry (minimax pinned fiat/usd; the H3 model)
# ---------------------------------------------------------------------------


def test_minimax_model_registered_fiat_usd() -> None:
    from sfvf.providers import PROVIDERS

    assert PROVIDERS["minimax"].meter_kind == "fiat" and PROVIDERS["minimax"].unit == "usd"
    provider, model = resolve(_MODEL)
    assert provider.id == "minimax" and model.kind == "video" and model.slug == _SLUG
    assert {"video.generate", "video.refs", "video.first_frame"} <= model.capabilities
    assert "video.generate" in capabilities_offered({"MINIMAX_API_KEY"})


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_generate_dry_run_makes_no_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_r: httpx2.Request, _s: list[httpx2.Request]) -> httpx2.Response:
        raise AssertionError("dry_run must not hit the network")

    seen = _install_mock(monkeypatch, boom)
    ctx = _ctx(tmp_path, dry_run=True)
    out = _run(ctx, lambda: media.video.generate("a fox", model=_MODEL, duration_s=2.0))
    assert (tmp_path / out).is_file()
    assert seen == []


# ---------------------------------------------------------------------------
# Real text-to-video — submit / poll / download / metered cost
# ---------------------------------------------------------------------------


def test_generate_real_submits_polls_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _completed_handler(polls_before_done=1))
    ctx = _ctx(tmp_path, dry_run=False)
    out = _run(
        ctx,
        lambda: media.video.generate(
            "a fox", model=_MODEL, duration_s=4.0, extra={"resolution": "768P"}
        ),
    )
    assert (tmp_path / out).read_bytes() == _MP4

    submit = next(r for r in seen if r.method == "POST")
    assert submit.url.path == "/v2/video_generation"
    assert submit.headers.get("authorization") == f"Bearer {_KEY}"
    body = _submit_body(seen)
    assert body["model"] == _SLUG
    assert body["content"][0] == {"type": "text", "text": "a fox"}
    assert body.get("resolution") == "768P"  # passthrough via extra
    assert any(
        r.method == "GET" and r.url.path.startswith("/v2/query/video_generation/") for r in seen
    )
    assert any(r.method == "GET" and r.url.path == "/out/vid.mp4" for r in seen)


def test_generate_real_records_a_metered_cost_from_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    _run(ctx, lambda: media.video.generate("a fox", model=_MODEL, duration_s=4.0))

    _, model = resolve(_MODEL)
    expected = _SECONDS * model.price.amount
    events = _cost_events(capsys.readouterr().out)
    assert events
    event = events[-1]
    assert event["meter"] == "minimax" and event["unit"] == "usd"
    assert event["source"] == "metered"
    assert event["amount"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Reference / frame images -> content items with role
# ---------------------------------------------------------------------------


def test_first_frame_becomes_a_role_content_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "artifacts" / "a.png").write_bytes(b"\x89PNG\r\n\x1a\nAAA")

    _run(
        ctx,
        lambda: media.video.generate(
            "a fox", model=_MODEL, first_frame="artifacts/a.png", duration_s=4.0
        ),
    )
    items = _submit_body(seen)["content"]
    by_role = {it.get("role"): it for it in items if it["type"] == "image_url"}
    assert by_role["first_frame"]["image_url"]["url"].startswith("data:image/png;base64,")


def test_ref_url_passes_through_as_reference_image(
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
            duration_s=4.0,
        ),
    )
    items = [it for it in _submit_body(seen)["content"] if it["type"] == "image_url"]
    assert any(
        it["image_url"]["url"] == "https://cdn.example.test/sheet.png"
        and it.get("role") == "reference_image"
        for it in items
    )


# ---------------------------------------------------------------------------
# Refusals — before any spend
# ---------------------------------------------------------------------------


def test_refs_on_a_model_without_the_capability_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sfvf.providers import registry
    from sfvf.providers.registry import Model, PriceHint

    monkeypatch.setitem(
        registry.MODELS,
        "minimax/no-refs",
        Model(
            id="minimax/no-refs",
            provider="minimax",
            slug="no-refs",
            kind="video",
            capabilities=frozenset({"video.generate"}),
            label="No Refs",
            price=PriceHint("usd", "per_second", 0.05, "test"),
        ),
    )
    seen = _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    with pytest.raises(CapabilityError):
        _run(
            ctx,
            lambda: media.video.generate(
                "x",
                model="minimax/no-refs",
                refs=[{"kind": "character", "path": "https://x/s.png"}],
            ),
        )
    assert seen == []


def test_generate_missing_key_raises_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False, secrets={})
    with pytest.raises(KeyError):
        _run(ctx, lambda: media.video.generate("x", model=_MODEL, duration_s=4.0))
    assert seen == []


def test_generate_requires_an_active_context() -> None:
    with pytest.raises(RuntimeError):
        media.video.generate("x", model=_MODEL, duration_s=4.0)
