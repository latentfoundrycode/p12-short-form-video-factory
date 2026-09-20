"""Frozen contract — Stage P hardening: scrub the response body from auth-failure errors.

Manifested live during the P-A/P-B smokes: on a 401 the provider (OpenAI) echoed the
*submitted* API key back in the response body, and `_http.request()` put that body — via
`_truncate(response.text)` — straight into `AdapterError.detail`, so the wrong key surfaced in the
error and any log of it. The kit's existing hygiene contract (`test_providers_kit.py`) only proved
the auth *header* value and the *query string* never leak; it did not cover a credential the server
reflects in the *body*.

The fix, scoped to `sdk/sfvf/providers/_http.py::request()`:
  * on an authentication/authorization failure status (401, 403), raise AdapterError WITHOUT the raw
    response body — a fixed, non-echoing detail — while still naming provider, where, and status.
  * on every other non-2xx (400, 5xx, ...), keep the existing truncated-body detail: those bodies
    are diagnostic and carry no submitted credential; over-scrubbing them would blind us.

No live network — httpx2.MockTransport + an in-test RateLimiter, exactly like the kit contract.
"""

from __future__ import annotations

import httpx2
import pytest
from sfvf._ratelimit import RateLimiter
from sfvf.providers._auth import BearerAuth
from sfvf.providers._http import request
from sfvf.providers.base import AdapterError

# A credential the *server* reflects back in its 401/403 body (what OpenAI did live). It is distinct
# from the client-side auth header value so the test proves body-scrubbing, not header-hygiene.
_ECHOED_KEY = "sk-LEAKED-key-echoed-in-body-1234567890"


def _client(handler) -> httpx2.Client:
    return httpx2.Client(base_url="https://api.acme.test", transport=httpx2.MockTransport(handler))


def _idle_limiter() -> RateLimiter:
    return RateLimiter(sleep=lambda _s: None)


def _call(handler):
    return request(
        _client(handler),
        "POST",
        "/generate",
        provider="acme",
        auth=BearerAuth("client-side-token"),
        limiter=_idle_limiter(),
    )


@pytest.mark.parametrize("status", [401, 403])
def test_request_scrubs_the_reflected_credential_from_auth_failure_bodies(status: int) -> None:
    # The provider echoes the submitted key in the failure body, as observed live.
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"error": {"message": f"invalid key {_ECHOED_KEY}"}})

    with pytest.raises(AdapterError) as exc:
        _call(handler)

    message = str(exc.value)
    assert _ECHOED_KEY not in message  # the reflected credential must not reach the error
    assert exc.value.detail is not None and _ECHOED_KEY not in exc.value.detail
    assert "acme" in message  # still names the provider,
    assert "/generate" in message  # where it failed,
    assert str(status) in message  # and the status — diagnostics survive, the secret does not


def test_request_keeps_the_body_detail_on_a_server_error() -> None:
    # A 5xx body carries no submitted credential and is diagnostic: it must NOT be scrubbed, so the
    # fix stays scoped to auth-failure statuses rather than blinding every error.
    marker = "upstream-model-queue-overflow-xyz"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503, text=marker)

    with pytest.raises(AdapterError) as exc:
        _call(handler)

    assert marker in str(exc.value)  # non-auth bodies stay surfaced for debugging
    assert "503" in str(exc.value)


def test_request_redacts_the_submitted_credential_from_a_non_auth_error_body() -> None:
    # H50: a provider that reflects the Authorization header on a 400/5xx would leak the SUBMITTED
    # key — the 401/403 fixed-string path does not cover other statuses. The credential we sent
    # (both the full "Bearer <token>" and the bare <token>) is redacted from every non-2xx body,
    # while the rest of the diagnostic body survives.
    sent = "super-secret-sent-token-abcdef123456"
    marker = "upstream-queue-overflow-marker-xyz"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, text=f"error: {marker}; echoed Authorization: Bearer {sent}")

    with pytest.raises(AdapterError) as exc:
        request(
            _client(handler),
            "POST",
            "/generate",
            provider="acme",
            auth=BearerAuth(sent),
            limiter=_idle_limiter(),
        )

    message = str(exc.value)
    detail = exc.value.detail or ""
    assert sent not in message  # the submitted credential (token) is redacted from a non-auth body
    assert marker in detail  # the rest of the 5xx body is preserved for diagnostics
    assert "500" in message
