"""Frozen contract — Stage P, P-B refactor R2: the shared async poll frame.

The four async adapters (byteplus / minimax / bfl / veo) hand-rolled the same submit-then-poll loop:
`deadline = now + timeout; while True: if timed out -> raise; request+parse; classify; heartbeat?;
sleep(interval)`. This extracts that FRAME into `sfvf.providers._poll.poll_until`, leaving each
provider's terminal-state classification and result extraction in the adapter (via an `is_done`
callback that returns True on completion, False while pending, and may raise its own AdapterError
on a terminal failure). This contract pins the frame directly — including the timeout branch, which
was previously unexercised in every adapter.

Everything runs against httpx2.MockTransport — no live network.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest
from sfvf.providers._auth import BearerAuth
from sfvf.providers._poll import poll_until
from sfvf.providers.base import AdapterError

_BASE = "https://poll.test"


def _client(handler) -> tuple[httpx2.Client, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request, seen)

    return httpx2.Client(base_url=_BASE, transport=httpx2.MockTransport(wrapped)), seen


def _poll(
    client,
    *,
    is_done,
    method="GET",
    json=None,
    heartbeat=None,
    interval=0.0,
    timeout=30.0,
    timeout_detail="task timed out",
):
    return poll_until(
        client,
        method=method,
        path="/op",
        provider="testprov",
        auth=BearerAuth("k"),
        is_done=is_done,
        json=json,
        heartbeat=heartbeat,
        interval=interval,
        timeout=timeout,
        timeout_detail=timeout_detail,
    )


def test_returns_payload_when_done_immediately() -> None:
    def handler(_r: httpx2.Request, _s: list[httpx2.Request]) -> httpx2.Response:
        return httpx2.Response(200, json={"status": "done", "value": 1})

    client, seen = _client(handler)
    with client:
        payload = _poll(client, is_done=lambda p: p.get("status") == "done")
    assert payload == {"status": "done", "value": 1}
    assert len(seen) == 1


def test_polls_while_pending_then_returns_done() -> None:
    def handler(_r: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        if len(seen) <= 2:
            return httpx2.Response(200, json={"status": "running"})
        return httpx2.Response(200, json={"status": "done"})

    client, seen = _client(handler)
    with client:
        payload = _poll(client, is_done=lambda p: p.get("status") == "done")
    assert payload["status"] == "done"
    assert len(seen) == 3


def test_is_done_may_raise_to_signal_terminal_failure() -> None:
    def handler(_r: httpx2.Request, _s: list[httpx2.Request]) -> httpx2.Response:
        return httpx2.Response(200, json={"status": "failed"})

    def is_done(payload: dict[str, Any]) -> bool:
        if payload.get("status") == "failed":
            raise AdapterError("testprov", where="poll", detail="task failed")
        return False

    client, _ = _client(handler)
    with client, pytest.raises(AdapterError) as excinfo:
        _poll(client, is_done=is_done)
    assert excinfo.value.detail == "task failed"


def test_timeout_raises_adaptererror_with_the_given_detail() -> None:
    def handler(_r: httpx2.Request, _s: list[httpx2.Request]) -> httpx2.Response:
        return httpx2.Response(200, json={"status": "running"})  # never done

    client, _ = _client(handler)
    with client, pytest.raises(AdapterError) as excinfo:
        _poll(
            client,
            is_done=lambda p: False,
            interval=0.0,
            timeout=0.0,
            timeout_detail="operation timed out",
        )
    assert excinfo.value.where == "poll"
    assert excinfo.value.detail == "operation timed out"


def test_default_timeout_detail_is_task_timed_out() -> None:
    def handler(_r: httpx2.Request, _s: list[httpx2.Request]) -> httpx2.Response:
        return httpx2.Response(200, json={"status": "running"})

    client, _ = _client(handler)
    with client, pytest.raises(AdapterError) as excinfo:
        _poll(client, is_done=lambda p: False, timeout=0.0)
    assert excinfo.value.detail == "task timed out"


def test_heartbeat_is_called_between_polls_and_optional() -> None:
    def handler(_r: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        if len(seen) <= 1:
            return httpx2.Response(200, json={"status": "running"})
        return httpx2.Response(200, json={"status": "done"})

    beats: list[int] = []
    client, _ = _client(handler)
    with client:
        _poll(
            client,
            is_done=lambda p: p.get("status") == "done",
            heartbeat=lambda: beats.append(1),
        )
    assert beats == [1]  # one pending poll -> one heartbeat, then done

    # heartbeat=None must not raise.
    def done_now(_r: httpx2.Request, _s: list[httpx2.Request]) -> httpx2.Response:
        return httpx2.Response(200, json={"status": "done"})

    client2, _ = _client(done_now)
    with client2:
        _poll(client2, is_done=lambda p: p.get("status") == "done", heartbeat=None)


def test_post_method_and_json_body_pass_through() -> None:
    def handler(_r: httpx2.Request, _s: list[httpx2.Request]) -> httpx2.Response:
        return httpx2.Response(200, json={"done": True})

    client, seen = _client(handler)
    with client:
        _poll(
            client,
            method="POST",
            json={"operationName": "op-1"},
            is_done=lambda p: bool(p.get("done")),
        )
    assert seen[0].method == "POST"
    assert json.loads(seen[0].read()) == {"operationName": "op-1"}
