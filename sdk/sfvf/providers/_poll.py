"""Shared async poll frame — deadline-bounded submit-then-poll loop for the media adapters."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .._ratelimit import LIMITER
from ._http import parse_json, request
from .base import AdapterError


def poll_until(
    client: Any,
    *,
    method: str,
    path: str,
    provider: str,
    auth: Any,
    is_done: Callable[[dict[str, Any]], bool],
    json: Any = None,
    heartbeat: Callable[[], None] | None = None,
    interval: float,
    timeout: float,
    timeout_detail: str = "task timed out",
) -> dict[str, Any]:
    """Poll `path` until `is_done(payload)` is True, then return that payload.

    `is_done` returns False while pending and may raise its own AdapterError on a terminal failure.
    Raises AdapterError(where="poll", detail=timeout_detail) if `timeout` seconds elapse first.
    """
    deadline = time.monotonic() + timeout
    while True:
        if time.monotonic() > deadline:
            raise AdapterError(provider, where="poll", detail=timeout_detail)
        response = request(
            client, method, path, provider=provider, auth=auth, limiter=LIMITER, json=json
        )
        payload = parse_json(response, provider=provider, where="poll")
        if is_done(payload):
            return payload
        if heartbeat is not None:
            heartbeat()
        time.sleep(interval)
