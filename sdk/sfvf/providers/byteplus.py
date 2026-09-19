"""BytePlus ModelArk Seedance adapter — async submit -> poll -> download, metered cost."""

from __future__ import annotations

import time
from typing import Any

from .._ratelimit import LIMITER
from ._auth import BearerAuth
from ._content import build_media_content
from ._http import download_bytes, parse_json, request
from .base import AdapterError, Cost, Output

_POLL_INTERVAL_S = 5.0  # monkeypatched to 0 in tests
_POLL_TIMEOUT_S = 1800.0
# rough pre-call reserve basis (actual reconciles from real usage)
_EST_TOKENS_PER_S = 50_000
_TERMINAL_FAIL = frozenset({"failed", "canceled"})


def _client(base_url: str) -> Any:
    import httpx2

    return httpx2.Client(base_url=base_url, timeout=60.0)


def video_estimate(model: Any, duration_s: float | None, extra: dict[str, Any] | None) -> float:
    return float(model.price.amount * _EST_TOKENS_PER_S * (duration_s or 5.0) / 1_000_000)


def generate_video(
    prompt: str,
    *,
    model: Any,
    provider: Any,
    first_frame_url: str | None,
    last_frame_url: str | None,
    ref_urls: list[str],
    duration_s: float | None,
    extra: dict[str, Any] | None,
    secrets: dict[str, str],
    ctx: Any,
) -> tuple[Output, Cost]:
    auth = BearerAuth(secrets["BYTEPLUS_ARK_API_KEY"])
    content = build_media_content(prompt, first_frame_url, last_frame_url, ref_urls)
    body: dict[str, Any] = {"model": model.slug, "content": content}
    if duration_s is not None:
        body["duration"] = round(duration_s)
    body.update(extra or {})  # ratio / resolution / seed / watermark / generate_audio
    with _client(provider.base_url) as client:
        submit = request(
            client,
            "POST",
            "/contents/generations/tasks",
            provider="byteplus",
            auth=auth,
            limiter=LIMITER,
            json=body,
        )
        task_id = parse_json(submit, provider="byteplus", where="submit")["id"]
        deadline = time.monotonic() + _POLL_TIMEOUT_S
        while True:
            if time.monotonic() > deadline:
                raise AdapterError("byteplus", where="poll", detail="task timed out")
            poll = request(
                client,
                "GET",
                f"/contents/generations/tasks/{task_id}",
                provider="byteplus",
                auth=auth,
                limiter=LIMITER,
            )
            payload = parse_json(poll, provider="byteplus", where="poll")
            status = payload.get("status")
            if status == "succeeded":
                break
            if status in _TERMINAL_FAIL:
                raise AdapterError("byteplus", where="poll", detail=f"task {status}")
            ctx.heartbeat("video", waiting_on="byteplus")
            time.sleep(_POLL_INTERVAL_S)
        try:
            video_url = payload["content"]["video_url"]
        except (KeyError, TypeError) as exc:
            raise AdapterError("byteplus", where="poll", detail="no video_url in result") from exc
        data = download_bytes(client, video_url, provider="byteplus", media="video")
    total_tokens = float((payload.get("usage") or {}).get("total_tokens") or 0.0)
    amount = total_tokens / 1_000_000 * model.price.amount
    return Output(data=data, media_type="video/mp4"), Cost(amount=amount, source="metered")
