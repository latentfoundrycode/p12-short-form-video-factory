"""Frozen contract — Stage P, P-5b: the Google Veo video adapter (Vertex, async).

Veo sits behind the media.video router. It is the async half of the Google adapter (the sync image
half is P-5a, in the same `google.py`): service-account OAuth via the existing `GoogleSaAuth`,
regional Vertex host, project read from the SA-JSON's `project_id`, region from the Provider row.

Flow: SUBMIT `POST :predictLongRunning` with instances[{prompt, image?:{bytesBase64Encoded,
mimeType}}] and parameters{durationSeconds, aspectRatio?, sampleCount:1,
personGeneration:"allow_adult"} -> {name: <operation resource path>}; POLL
`POST :fetchPredictOperation` with {operationName} until done == true (a top-level `error` on a
done operation is a failure); the MP4 comes back inline at
response.videos[0].{bytesBase64Encoded, mimeType} (no storageUri set). Cost is priced
($/second x requested duration; Veo default 8 s).

Capabilities are {video.generate, video.first_frame} ONLY -- first_frame maps to
instances[].image (a local file arrives as a `data:` URI from the shared refs->URL bridge and is
decoded to raw base64; an http(s) URL is fetched and encoded). Multi-reference (video.refs) and
last-frame are NOT offered: refs are refused by the router, and a last_frame is refused by the
adapter -- both before any spend.

HTTP is mocked via httpx2.MockTransport by monkeypatching `sfvf.providers.google._transport` (serves
the SA token exchange, predictLongRunning, fetchPredictOperation, and any http frame fetch) and
`sfvf.providers.google._POLL_INTERVAL_S`. No live network; ephemeral in-test RSA key.

The one shape read less verbatim from the docs (inline video bytes at response.videos[]) is
pinned to the best-documented reading and confirmed at the live smoke.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx2
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sfvf import media
from sfvf.context import BudgetConfig, Context, ContextFile, ContextPaths
from sfvf.providers import CapabilityError, capabilities_offered, resolve

_MODEL = "google/veo-3.1-generate-001"
_SLUG = "veo-3.1-generate-001"
_TOKEN = "ya29.mock-access-token-not-real"
_TOKEN_URI = "https://oauth2.googleapis.test/token"
_MP4 = b"\x00\x00\x00\x18ftypmp42FAKE-VEO-VIDEO"
_OP = (
    "projects/sfvf-test-project/locations/us-central1"
    "/publishers/google/models/veo-3.1-generate-001/operations/op-123"
)
_FRAME_URL = "https://cdn.example.test/frame.png"
_FRAME_BYTES = b"\x89PNG\r\n\x1a\nHTTP-FRAME"


def _sa_json() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "sfvf-test-project",
            "private_key_id": "kid-1",
            "private_key": pem,
            "client_email": "sfvf@sfvf-test-project.iam.gserviceaccount.test",
            "client_id": "123",
            "token_uri": _TOKEN_URI,
        }
    )


_SA_JSON = _sa_json()


def _ctx(tmp: Path, *, dry_run: bool, secrets: dict[str, object] | None = None) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            secrets={"GOOGLE_SA_JSON": _SA_JSON} if secrets is None else secrets,
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
            budget=BudgetConfig(
                ledger_path=tmp / "budget" / "ledger.jsonl",
                per_day={"google": 1_000_000.0},
                estimates={},
            ),
        )
    )


def _video_response() -> dict:
    return {
        "name": _OP,
        "done": True,
        "response": {
            "videos": [
                {"bytesBase64Encoded": base64.b64encode(_MP4).decode(), "mimeType": "video/mp4"}
            ]
        },
    }


def _completed_handler(polls_before_done: int = 1):
    """token; predictLongRunning -> name; fetchPredictOperation running N times then done."""

    def handler(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        path = request.url.path
        if request.method == "POST" and path == "/token":
            return httpx2.Response(200, json={"access_token": _TOKEN, "expires_in": 3600})
        if request.method == "POST" and path.endswith(":predictLongRunning"):
            return httpx2.Response(200, json={"name": _OP})
        if request.method == "POST" and path.endswith(":fetchPredictOperation"):
            n = sum(
                1
                for r in seen
                if r.method == "POST" and r.url.path.endswith(":fetchPredictOperation")
            )
            if n <= polls_before_done:
                return httpx2.Response(200, json={"name": _OP, "done": False})
            return httpx2.Response(200, json=_video_response())
        if request.method == "GET" and request.url.host == "cdn.example.test":
            return httpx2.Response(200, content=_FRAME_BYTES)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx2.Request]:
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request, seen)

    def _transport() -> httpx2.MockTransport:
        return httpx2.MockTransport(wrapped)

    from sfvf.providers import google as google_adapter

    monkeypatch.setattr(google_adapter, "_transport", _transport)
    monkeypatch.setattr(google_adapter, "_POLL_INTERVAL_S", 0.0)
    return seen


def _run(ctx: Context, fn):
    from sfvf._runtime import reset_active, set_active

    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def _submit_body(seen: list[httpx2.Request]) -> dict:
    call = next(r for r in seen if r.url.path.endswith(":predictLongRunning"))
    return json.loads(call.read())


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


def test_veo_model_registered_fiat_usd() -> None:
    from sfvf.providers import PROVIDERS

    assert PROVIDERS["google"].meter_kind == "fiat" and PROVIDERS["google"].unit == "usd"
    provider, model = resolve(_MODEL)
    assert provider.id == "google" and model.kind == "video" and model.slug == _SLUG
    assert {"video.generate", "video.first_frame"} <= model.capabilities
    assert "video.refs" not in model.capabilities
    assert "video.generate" in capabilities_offered({"GOOGLE_SA_JSON"})


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_generate_dry_run_makes_no_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_r: httpx2.Request, _s: list[httpx2.Request]) -> httpx2.Response:
        raise AssertionError("dry_run must not hit the network")

    seen = _install_mock(monkeypatch, boom)
    ctx = _ctx(tmp_path, dry_run=True)
    out = _run(ctx, lambda: media.video.generate("a fox", model=_MODEL, duration_s=6.0))
    assert (tmp_path / out).is_file()
    assert seen == []


# ---------------------------------------------------------------------------
# Real submit / poll / download
# ---------------------------------------------------------------------------


def test_generate_real_submits_polls_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _completed_handler(polls_before_done=1))
    ctx = _ctx(tmp_path, dry_run=False)
    out = _run(ctx, lambda: media.video.generate("a fox", model=_MODEL, duration_s=6.0))
    assert (tmp_path / out).read_bytes() == _MP4

    submit = next(r for r in seen if r.url.path.endswith(":predictLongRunning"))
    assert submit.url.host == "us-central1-aiplatform.googleapis.com"
    assert submit.url.path == (
        "/v1/projects/sfvf-test-project/locations/us-central1"
        "/publishers/google/models/veo-3.1-generate-001:predictLongRunning"
    )
    assert submit.headers.get("authorization") == f"Bearer {_TOKEN}"
    body = _submit_body(seen)
    assert body["instances"][0]["prompt"] == "a fox"
    assert body["parameters"]["sampleCount"] == 1
    assert body["parameters"]["personGeneration"] == "allow_adult"
    assert body["parameters"]["durationSeconds"] == 6
    poll = next(r for r in seen if r.url.path.endswith(":fetchPredictOperation"))
    assert json.loads(poll.read())["operationName"] == _OP


def test_generate_records_a_priced_cost_from_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    _run(ctx, lambda: media.video.generate("a fox", model=_MODEL, duration_s=6.0))

    _, model = resolve(_MODEL)
    events = _cost_events(capsys.readouterr().out)
    assert events
    event = events[-1]
    assert event["meter"] == "google" and event["unit"] == "usd"
    assert event["source"] == "priced"
    assert event["amount"] == pytest.approx(6.0 * model.price.amount)


# ---------------------------------------------------------------------------
# First-frame conditioning -> instances[].image.bytesBase64Encoded
# ---------------------------------------------------------------------------


def test_first_frame_local_file_becomes_inline_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "artifacts" / "a.png").write_bytes(b"\x89PNG\r\n\x1a\nLOCAL")

    _run(
        ctx,
        lambda: media.video.generate(
            "a fox", model=_MODEL, first_frame="artifacts/a.png", duration_s=6.0
        ),
    )
    image = _submit_body(seen)["instances"][0]["image"]
    assert image["bytesBase64Encoded"] == base64.b64encode(b"\x89PNG\r\n\x1a\nLOCAL").decode()
    assert image["mimeType"] == "image/png"


def test_first_frame_http_url_is_fetched_and_inlined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    _run(
        ctx,
        lambda: media.video.generate("a fox", model=_MODEL, first_frame=_FRAME_URL, duration_s=6.0),
    )
    image = _submit_body(seen)["instances"][0]["image"]
    assert image["bytesBase64Encoded"] == base64.b64encode(_FRAME_BYTES).decode()
    assert any(r.method == "GET" and r.url.host == "cdn.example.test" for r in seen)


# ---------------------------------------------------------------------------
# Refusals — before any spend
# ---------------------------------------------------------------------------


def test_refs_are_refused_by_the_router_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    with pytest.raises(CapabilityError):
        _run(
            ctx,
            lambda: media.video.generate(
                "a fox",
                model=_MODEL,
                refs=[{"kind": "character", "path": "https://x/s.png"}],
                duration_s=6.0,
            ),
        )
    assert seen == []


def test_last_frame_is_refused_before_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "artifacts" / "z.png").write_bytes(b"\x89PNG\r\n\x1a\nZ")
    with pytest.raises(CapabilityError):
        _run(
            ctx,
            lambda: media.video.generate(
                "a fox", model=_MODEL, last_frame="artifacts/z.png", duration_s=6.0
            ),
        )
    assert not any(r.url.path.endswith(":predictLongRunning") for r in seen)


def test_operation_error_raises_adaptererror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sfvf.providers.base import AdapterError

    def failing(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        path = request.url.path
        if path == "/token":
            return httpx2.Response(200, json={"access_token": _TOKEN, "expires_in": 3600})
        if path.endswith(":predictLongRunning"):
            return httpx2.Response(200, json={"name": _OP})
        return httpx2.Response(
            200, json={"name": _OP, "done": True, "error": {"code": 3, "message": "bad"}}
        )

    _install_mock(monkeypatch, failing)
    ctx = _ctx(tmp_path, dry_run=False)
    with pytest.raises(AdapterError):
        _run(ctx, lambda: media.video.generate("a fox", model=_MODEL, duration_s=6.0))


def test_generate_missing_key_raises_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False, secrets={})
    with pytest.raises(KeyError):
        _run(ctx, lambda: media.video.generate("x", model=_MODEL, duration_s=6.0))
    assert seen == []


def test_generate_requires_an_active_context() -> None:
    with pytest.raises(RuntimeError):
        media.video.generate("x", model=_MODEL, duration_s=6.0)
