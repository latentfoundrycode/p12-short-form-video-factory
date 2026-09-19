"""MiniMax (Hailuo H3, v2) video adapter — async submit -> poll -> download; metered per second."""

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
_TERMINAL_FAIL = frozenset({"failed", "cancelled"})


def _client(base_url: str) -> Any:
    import httpx2

    return httpx2.Client(base_url=base_url, timeout=60.0)


def video_estimate(model: Any, duration_s: float | None, extra: dict[str, Any] | None) -> float:
    return float(model.price.amount * (duration_s or 5.0))  # $/s * seconds


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
    auth = BearerAuth(secrets["MINIMAX_API_KEY"])
    content = build_media_content(
        prompt, first_frame_url, last_frame_url, ref_urls, ref_role="reference_image"
    )
    body: dict[str, Any] = {"model": model.slug, "content": content}
    if duration_s is not None:
        body["duration"] = round(duration_s)
    body.update(extra or {})  # resolution / ratio passthrough
    with _client(provider.base_url) as client:
        submit = request(
            client,
            "POST",
            "/v2/video_generation",
            provider="minimax",
            auth=auth,
            limiter=LIMITER,
            json=body,
        )
        task_id = parse_json(submit, provider="minimax", where="submit")["task_id"]
        deadline = time.monotonic() + _POLL_TIMEOUT_S
        task: dict[str, Any] = {}
        while True:
            if time.monotonic() > deadline:
                raise AdapterError("minimax", where="poll", detail="task timed out")
            poll = request(
                client,
                "GET",
                f"/v2/query/video_generation/{task_id}",
                provider="minimax",
                auth=auth,
                limiter=LIMITER,
            )
            task = parse_json(poll, provider="minimax", where="poll").get("task") or {}
            status = task.get("status")
            if status == "succeeded":
                break
            if status in _TERMINAL_FAIL:
                raise AdapterError("minimax", where="poll", detail=f"task {status}")
            ctx.heartbeat("video", waiting_on="minimax")
            time.sleep(_POLL_INTERVAL_S)
        try:
            video_url = task["content"]["url"]
        except (KeyError, TypeError) as exc:
            raise AdapterError("minimax", where="poll", detail="no task.content.url") from exc
        data = download_bytes(client, video_url, provider="minimax", media="video")
    usage = task.get("usage") or {}
    seconds = float(
        usage.get("total_seconds") or usage.get("output_seconds") or (duration_s or 0.0)
    )
    amount = seconds * model.price.amount
    return Output(data=data, media_type="video/mp4"), Cost(amount=amount, source="metered")
