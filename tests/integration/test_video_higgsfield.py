"""B-5 contract: `media.video.generate` on Higgsfield's REST API, MOCKED HTTP only.

Higgsfield's documented REST API (Architecture §5.5, amended to REST/API-key per the Option-B
decision) is an async job lifecycle: POST a model endpoint (e.g. `/sora-2/text-to-video`) with
`Authorization: Key <id:secret>` -> `{request_id, status:"queued", status_url}`; poll
`GET /requests/{id}/status` until `status` is terminal (`completed` -> `video.url`; `failed`/
`nsfw`/`canceled` -> error); download the video from `video.url`. The adapter heartbeats while
polling (§2.8/§6.3) so a legitimately slow job isn't killed.

All exercised against `httpx2.MockTransport` — NO live network call, no OAuth, no key (only an
in-memory fake). `dry_run` is a genuine no-network stub: a real placeholder MP4 at zero cost.
Frame/ref-conditioned generation is a later increment; this one is text-to-video.
"""

import json
from pathlib import Path

import httpx2
import pytest
from sfvf import media
from sfvf._ffmpeg import probe
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths

_KEY = "hf-fake-id:hf-fake-secret-not-real"
_MODEL = "sora-2/text-to-video"
_DOWNLOAD_PATH = "/files/result.mp4"
_VIDEO_BYTES = b"\x00\x01FAKE-MP4-CONTENT-downloaded\x02\x03"


def _ctx(tmp: Path, *, dry_run: bool, secrets: dict[str, object] | None = None) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            secrets={"HIGGSFIELD_API_KEY": _KEY} if secrets is None else secrets,
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
        )
    )


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx2.Request]:
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request, seen)

    def _client() -> httpx2.Client:
        return httpx2.Client(
            base_url="https://api.higgsfield.ai", transport=httpx2.MockTransport(wrapped)
        )

    monkeypatch.setattr(media.video, "_http_client", _client)
    monkeypatch.setattr(media.video, "_POLL_INTERVAL_S", 0.0)
    return seen


def _run(ctx: Context, fn):
    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def _status(status: str, **extra) -> dict[str, object]:
    body: dict[str, object] = {
        "request_id": "req-123",
        "status": status,
        "status_url": "https://api.higgsfield.ai/requests/req-123/status",
        "cancel_url": "https://api.higgsfield.ai/requests/req-123/cancel",
    }
    body.update(extra)
    return body


def _completed_handler(polls_before_done: int = 2):
    """submit->queued; status->in_progress N times then completed; file->bytes."""

    def handler(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith(_MODEL):
            return httpx2.Response(200, json=_status("queued"))
        if request.method == "GET" and "/requests/" in path:
            n = sum(1 for r in seen if r.method == "GET" and "/requests/" in r.url.path)
            if n <= polls_before_done:
                return httpx2.Response(200, json=_status("in_progress"))
            return httpx2.Response(
                200,
                json=_status(
                    "completed", video={"url": f"https://api.higgsfield.ai{_DOWNLOAD_PATH}"}
                ),
            )
        if request.method == "GET" and path == _DOWNLOAD_PATH:
            return httpx2.Response(200, content=_VIDEO_BYTES)
        raise AssertionError(f"unexpected request: {request.method} {path}")

    return handler


def test_generate_dry_run_makes_no_call_and_returns_stub_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        raise AssertionError("dry_run video generation must not make any network call")

    seen = _install_mock(monkeypatch, boom)
    ctx = _ctx(tmp_path, dry_run=True)
    out = _run(ctx, lambda: media.video.generate("a cat", model=_MODEL, duration_s=2.0))

    assert isinstance(out, str)
    assert not Path(out).is_absolute()
    clip = tmp_path / out
    assert clip.is_file()
    assert abs(probe(clip).duration_s - 2.0) < 0.5  # a real placeholder clip of the right length
    assert seen == []


def test_generate_real_submits_polls_and_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _completed_handler(polls_before_done=2))
    ctx = _ctx(tmp_path, dry_run=False)
    out = _run(ctx, lambda: media.video.generate("a cat", model=_MODEL, duration_s=5.0))

    clip = tmp_path / out
    assert clip.is_file()
    assert clip.read_bytes() == _VIDEO_BYTES  # the downloaded result was saved

    submit = seen[0]
    assert submit.method == "POST"
    assert submit.url.path.endswith(_MODEL)
    assert submit.headers.get("authorization") == f"Key {_KEY}"
    assert json.loads(submit.read())["prompt"] == "a cat"
    # it polled the status endpoint until terminal, then fetched the file
    assert sum(1 for r in seen if r.method == "GET" and "/requests/" in r.url.path) >= 3
    assert any(r.method == "GET" and r.url.path == _DOWNLOAD_PATH for r in seen)


def test_generate_real_heartbeats_while_polling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_mock(monkeypatch, _completed_handler(polls_before_done=2))
    ctx = _ctx(tmp_path, dry_run=False)
    _run(ctx, lambda: media.video.generate("a cat", model=_MODEL, duration_s=5.0))

    events = []
    for line in capsys.readouterr().out.splitlines():
        s = line.strip()
        if s.startswith("{"):
            try:
                events.append(json.loads(s))
            except ValueError:
                continue
    assert any(e.get("t") == "heartbeat" for e in events)


def test_generate_real_failed_status_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        if request.method == "POST":
            return httpx2.Response(200, json=_status("queued"))
        return httpx2.Response(200, json=_status("failed", error="content policy"))

    _install_mock(monkeypatch, handler)
    ctx = _ctx(tmp_path, dry_run=False)
    with pytest.raises(RuntimeError):
        _run(ctx, lambda: media.video.generate("x", model=_MODEL, duration_s=5.0))


def test_generate_real_passes_extra_and_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _completed_handler(polls_before_done=0))
    ctx = _ctx(tmp_path, dry_run=False)
    _run(
        ctx,
        lambda: media.video.generate(
            "x", model=_MODEL, duration_s=8.0, extra={"aspect_ratio": "9:16", "seed": 7}
        ),
    )
    body = json.loads(seen[0].read())
    assert body["aspect_ratio"] == "9:16"
    assert body["seed"] == 7
    assert body.get("duration") == 8.0  # duration_s mapped into the request body


def test_generate_real_missing_key_raises_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        raise AssertionError("must fail on the missing key before any network call")

    seen = _install_mock(monkeypatch, boom)
    ctx = _ctx(tmp_path, dry_run=False, secrets={})
    with pytest.raises(KeyError):
        _run(ctx, lambda: media.video.generate("x", model=_MODEL, duration_s=5.0))
    assert seen == []


def test_generate_frame_conditioning_not_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock(monkeypatch, _completed_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    with pytest.raises(NotImplementedError):
        _run(
            ctx,
            lambda: media.video.generate(
                "x", model=_MODEL, duration_s=5.0, first_frame="artifacts/a.png"
            ),
        )


def test_generate_real_download_failure_raises_and_saves_no_corrupt_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A non-2xx on the DOWNLOAD must raise — never save the error body as the "video"
    # (a silent corrupt success would also poison the step cache).
    def handler(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        path = request.url.path
        if request.method == "POST":
            return httpx2.Response(200, json=_status("queued"))
        if "/requests/" in path:
            return httpx2.Response(
                200,
                json=_status(
                    "completed", video={"url": f"https://api.higgsfield.ai{_DOWNLOAD_PATH}"}
                ),
            )
        return httpx2.Response(500, content=b"error page")  # download fails

    _install_mock(monkeypatch, handler)
    ctx = _ctx(tmp_path, dry_run=False)
    with pytest.raises(RuntimeError):
        _run(ctx, lambda: media.video.generate("x", model=_MODEL, duration_s=5.0))
    artifacts = tmp_path / "artifacts"
    if artifacts.exists():
        assert all(p.read_bytes() != b"error page" for p in artifacts.glob("video-*.mp4"))


def test_generate_real_poll_failure_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A non-2xx on a POLL must raise a clear error, not be parsed as a successful status body.
    def handler(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        if request.method == "POST":
            return httpx2.Response(200, json=_status("queued"))
        return httpx2.Response(500, json={"error": "server error"})  # poll fails

    _install_mock(monkeypatch, handler)
    ctx = _ctx(tmp_path, dry_run=False)
    with pytest.raises(RuntimeError):
        _run(ctx, lambda: media.video.generate("x", model=_MODEL, duration_s=5.0))


def test_generate_requires_active_context() -> None:
    with pytest.raises(RuntimeError):
        media.video.generate("x", model=_MODEL, duration_s=5.0)
