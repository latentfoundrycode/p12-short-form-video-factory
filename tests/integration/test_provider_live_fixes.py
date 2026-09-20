"""Frozen contracts — Stage P live-smoke corrections (P-B attended smoke, 2026-09-20).

The mock-based P-6/P-7 unit contracts passed while the real providers rejected the calls, because
each mock happened to match the adapter's own (wrong) assumption. These pin the corrected behaviour
the LIVE smoke proved necessary:

  * BFL: the async submit returns a `polling_url` on a REGIONAL host (e.g. api.us1.bfl.ai); the
    adapter must poll THAT url. Polling the hardcoded global `/v1/get_result` returns 404
    "Task not found" — the exact live failure. The P-6 spec said "poll polling_url"; the code
    hardcoded the path, and the old mock hid it by putting polling_url on the same host+path.
  * MiniMax: `POST /v2/video_generation` REQUIRES a `resolution` parameter; omitting it is a 400
    ("invalid params ... expr_path=resolution ... missing required parameter"). The adapter must
    send a default resolution when the caller passes none via `extra`.

httpx2.MockTransport, no live network, fake keys — same harness as the P-6/P-7 contracts.
"""

from __future__ import annotations

import json

import httpx2
import pytest
from sfvf.providers import bfl as bfl_adapter
from sfvf.providers import minimax as mm_adapter
from sfvf.providers import resolve
from sfvf.providers.base import AdapterError

_BFL_KEY = "bfl-fake-not-real"
_MM_KEY = "mm-fake-not-real"
_PNG = b"\x89PNG\r\n\x1a\nFAKE"
_MP4 = b"\x00\x00\x00\x18ftypmp42FAKE"


def _install(monkeypatch, module, handler):
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request, seen)

    def _client(base_url: str) -> httpx2.Client:
        return httpx2.Client(base_url=base_url, transport=httpx2.MockTransport(wrapped))

    monkeypatch.setattr(module, "_client", _client)
    monkeypatch.setattr(module, "_POLL_INTERVAL_S", 0.0)
    return seen


def test_bfl_polls_the_regional_polling_url(monkeypatch) -> None:
    provider, model = resolve("bfl/flux-1.1-pro")
    sample = "https://bfl-cdn.example.test/s.png"
    polling_url = "https://api.us1.bfl.ai/v1/get_result?id=bfl-xyz"

    def handler(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        method, host, path = request.method, request.url.host, request.url.path
        if method == "POST" and path.startswith("/v1/flux"):
            return httpx2.Response(200, json={"id": "bfl-xyz", "polling_url": polling_url})
        # The result exists ONLY at the regional polling_url host BFL returned:
        if method == "GET" and host == "api.us1.bfl.ai" and path == "/v1/get_result":
            return httpx2.Response(
                200, json={"id": "bfl-xyz", "status": "Ready", "result": {"sample": sample}}
            )
        # A poll to the GLOBAL submit host is what real BFL rejects with 404 "Task not found":
        if method == "GET" and path == "/v1/get_result":
            return httpx2.Response(404, json={"id": "bfl-xyz", "status": "Task not found"})
        if method == "GET" and path == "/s.png":
            return httpx2.Response(200, content=_PNG)
        raise AssertionError(f"unexpected {method} {host}{path}")

    seen = _install(monkeypatch, bfl_adapter, handler)
    out = bfl_adapter.generate(
        "a cat", model=model, provider=provider, size=None, secrets={"BFL_API_KEY": _BFL_KEY}
    )
    assert out.data == _PNG
    assert any(r.method == "GET" and r.url.host == "api.us1.bfl.ai" for r in seen), (
        "adapter must poll the returned regional polling_url, not the global /v1/get_result"
    )


class _Ctx:
    def heartbeat(self, *args: object, **kwargs: object) -> None:
        return None


def test_minimax_sends_a_default_resolution(monkeypatch) -> None:
    provider, model = resolve("minimax/hailuo-h3")
    video_url = "https://cdn.minimax.example.test/o.mp4"
    bodies: list[dict] = []

    def handler(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        method, path = request.method, request.url.path
        if method == "POST" and path == "/v2/video_generation":
            bodies.append(json.loads(request.read()))
            return httpx2.Response(200, json={"task_id": "mm-1", "base_resp": {"status_code": 0}})
        if method == "GET" and path.startswith("/v2/query/video_generation/"):
            return httpx2.Response(
                200,
                json={
                    "task": {
                        "id": "mm-1",
                        "status": "succeeded",
                        "content": {"url": video_url},
                        "usage": {"total_seconds": 4.0},
                    },
                    "base_resp": {"status_code": 0},
                },
            )
        if method == "GET" and path == "/o.mp4":
            return httpx2.Response(200, content=_MP4)
        raise AssertionError(f"unexpected {method} {path}")

    _install(monkeypatch, mm_adapter, handler)
    out, _cost = mm_adapter.generate_video(
        "a wave",
        model=model,
        provider=provider,
        first_frame_url=None,
        last_frame_url=None,
        ref_urls=[],
        duration_s=None,
        extra=None,
        secrets={"MINIMAX_API_KEY": _MM_KEY},
        ctx=_Ctx(),
    )
    assert out.data == _MP4
    assert bodies, "no submit body captured"
    assert "resolution" in bodies[0], (
        "submit must carry a default resolution — MiniMax 400s without it"
    )


def test_minimax_sends_default_ratio_and_duration(monkeypatch) -> None:
    # The live smoke proved MiniMax also 400s on a missing `ratio` ("required for t2va, cannot be
    # 'adaptive'"); and a video request should carry a concrete `duration` for predictable metered
    # cost. Both must be present by default (overridable via extra / duration_s).
    provider, model = resolve("minimax/hailuo-h3")
    video_url = "https://cdn.minimax.example.test/o2.mp4"
    bodies: list[dict] = []

    def handler(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        method, path = request.method, request.url.path
        if method == "POST" and path == "/v2/video_generation":
            bodies.append(json.loads(request.read()))
            return httpx2.Response(200, json={"task_id": "mm-2", "base_resp": {"status_code": 0}})
        if method == "GET" and path.startswith("/v2/query/video_generation/"):
            return httpx2.Response(
                200,
                json={
                    "task": {
                        "id": "mm-2",
                        "status": "succeeded",
                        "content": {"url": video_url},
                        "usage": {"total_seconds": 6.0},
                    },
                    "base_resp": {"status_code": 0},
                },
            )
        if method == "GET" and path == "/o2.mp4":
            return httpx2.Response(200, content=_MP4)
        raise AssertionError(f"unexpected {method} {path}")

    _install(monkeypatch, mm_adapter, handler)
    mm_adapter.generate_video(
        "a wave",
        model=model,
        provider=provider,
        first_frame_url=None,
        last_frame_url=None,
        ref_urls=[],
        duration_s=None,
        extra=None,
        secrets={"MINIMAX_API_KEY": _MM_KEY},
        ctx=_Ctx(),
    )
    assert bodies, "no submit body captured"
    body = bodies[0]
    assert "ratio" in body, "submit must carry a default ratio — MiniMax 400s without it for t2va"
    assert "duration" in body, "submit must carry a duration for predictable metered cost"


@pytest.mark.parametrize(
    "bad_polling_url",
    [
        "https://evil.example.com/v1/get_result?id=bfl-xyz",  # foreign host
        "http://api.bfl.ai/v1/get_result?id=bfl-xyz",  # bfl host but plaintext http
    ],
)
def test_bfl_refuses_a_polling_url_not_on_an_https_bfl_host(
    monkeypatch, bad_polling_url: str
) -> None:
    # H51: request() merges the x-key (BFL_API_KEY) header onto EVERY request, including the poll to
    # the provider-returned polling_url. A spoofed/MITM'd submit response could name a foreign or
    # plaintext host and harvest the key. The adapter must refuse a polling_url that is not https
    # on a *.bfl.ai host BEFORE polling — so the key never leaves BFL-designated https hosts.
    provider, model = resolve("bfl/flux-1.1-pro")

    def handler(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        method, path = request.method, request.url.path
        if method == "POST" and path.startswith("/v1/flux"):
            return httpx2.Response(200, json={"id": "bfl-xyz", "polling_url": bad_polling_url})
        # If the adapter (unguarded) polls the bad host, answer Ready so it would "succeed" — which
        # means the key already left. The test asserts below that no such request was ever made.
        return httpx2.Response(
            200, json={"id": "bfl-xyz", "status": "Ready", "result": {"sample": bad_polling_url}}
        )

    seen = _install(monkeypatch, bfl_adapter, handler)
    with pytest.raises(AdapterError) as exc:
        bfl_adapter.generate(
            "a cat", model=model, provider=provider, size=None, secrets={"BFL_API_KEY": _BFL_KEY}
        )
    assert "bfl" in str(exc.value)
    # The credential-bearing poll must NOT have reached the disallowed host.
    bad_host = httpx2.URL(bad_polling_url).host
    assert not any(r.method == "GET" and r.url.host == bad_host for r in seen), (
        "adapter must refuse the polling_url before sending the x-key to a disallowed host"
    )


def test_minimax_raises_a_clean_error_on_a_200_with_base_resp_failure(monkeypatch) -> None:
    # MiniMax signals some submit failures with HTTP 200 + base_resp.status_code != 0 and no
    # task_id (P-7 NOTED). The adapter must raise a clean AdapterError, not a raw KeyError on
    # ["task_id"].
    provider, model = resolve("minimax/hailuo-h3")

    def handler(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        if request.method == "POST" and request.url.path == "/v2/video_generation":
            return httpx2.Response(
                200, json={"base_resp": {"status_code": 1002, "status_msg": "insufficient balance"}}
            )
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    _install(monkeypatch, mm_adapter, handler)
    with pytest.raises(AdapterError) as exc:
        mm_adapter.generate_video(
            "a wave",
            model=model,
            provider=provider,
            first_frame_url=None,
            last_frame_url=None,
            ref_urls=[],
            duration_s=None,
            extra=None,
            secrets={"MINIMAX_API_KEY": _MM_KEY},
            ctx=_Ctx(),
        )
    assert "minimax" in str(exc.value)
