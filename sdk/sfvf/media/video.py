from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from .._ffmpeg import color_bars
from .._ratelimit import LIMITER as _LIMITER
from .._runtime import current_context
from .graphics import _artifact, _sha8

if TYPE_CHECKING:
    import httpx2

_LIMITER.configure("higgsfield", max_concurrency=2, min_interval_s=0.0)

_HTTP_TIMEOUT_S = 60.0
_POLL_INTERVAL_S = 2.0
_POLL_TIMEOUT_S = 1800.0
_DEFAULT_DURATION_S = 5.0
_WIDTH = 1080
_HEIGHT = 1920
_FPS = 30
_TERMINAL_ERRORS = frozenset({"failed", "nsfw", "canceled"})


def _http_client() -> httpx2.Client:
    try:
        import httpx2
    except ImportError as exc:
        raise RuntimeError(
            "media.video.generate requires the 'httpx2' package. Install the SDK "
            "'openrouter' extra: pip install 'sfvf[openrouter]'."
        ) from exc
    return httpx2.Client(
        base_url="https://api.higgsfield.ai",
        timeout=_HTTP_TIMEOUT_S,
    )


def generate(
    prompt: str,
    *,
    model: str,
    first_frame: str | None = None,
    last_frame: str | None = None,
    refs: list[Any] | None = None,
    duration_s: float | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    ctx = current_context()
    dest, rel = _artifact(ctx, f"video-{_sha8([prompt, model, duration_s, extra])}.mp4")
    if ctx.dry_run:
        color_bars(
            dest,
            duration_s=duration_s or _DEFAULT_DURATION_S,
            width=_WIDTH,
            height=_HEIGHT,
            fps=_FPS,
        )
        return rel

    if first_frame is not None or last_frame is not None or refs is not None:
        raise NotImplementedError(
            "frame/ref-conditioned generation is not yet supported by the Higgsfield adapter"
        )

    key = ctx.secret("HIGGSFIELD_API_KEY")
    body: dict[str, Any] = {"prompt": prompt}
    if duration_s is not None:
        body["duration"] = duration_s
    body.update(extra or {})

    with _http_client() as client:
        with _LIMITER.slot("higgsfield"):
            resp = client.post(
                "/" + model,
                headers={"Authorization": f"Key {key}"},
                json=body,
            )
        if resp.status_code // 100 != 2:
            raise RuntimeError(f"Higgsfield submit {resp.status_code}: {resp.text}")
        submitted: dict[str, Any] = resp.json()
        request_id = submitted["request_id"]
        status_url = submitted["status_url"]

        deadline = time.monotonic() + _POLL_TIMEOUT_S
        completed: dict[str, Any]
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"Higgsfield poll timed out after {_POLL_TIMEOUT_S:.0f}s "
                    f"(request_id={request_id})"
                )
            poll = client.get(status_url)
            if poll.status_code // 100 != 2:
                raise RuntimeError(f"Higgsfield poll {poll.status_code}: {poll.text}")
            payload: dict[str, Any] = poll.json()
            status = payload["status"]
            if status == "completed":
                completed = payload
                break
            if status in _TERMINAL_ERRORS:
                raise RuntimeError(f"Higgsfield {status}: {payload.get('error')}")
            ctx.heartbeat("video", waiting_on="higgsfield")
            time.sleep(_POLL_INTERVAL_S)

        download = client.get(completed["video"]["url"])
        if download.status_code // 100 != 2:
            raise RuntimeError(f"Higgsfield download {download.status_code}: {download.text}")
        dest.write_bytes(download.content)

    ctx.log(f"Higgsfield video model={model} request_id={request_id}")
    return rel
