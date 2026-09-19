"""Frozen contract — Stage P, P-2: the adapter kit (auth + HTTP + rate-limit hardening).

The provider layer's adapters share one kit so auth, retrying HTTP, and error hygiene are written
once (docs/PROVIDER_LAYER_PLAN.md §3.3). This increment lands, in sdk/sfvf/providers/:
  * base.py  — AdapterError (a RuntimeError so existing pytest.raises(RuntimeError) contracts hold)
               and the Cost value (amount + source in {"reported","metered","priced"}).
  * _auth.py — four auth strategies: BearerAuth, HeaderAuth (x-key / x-goog-api-key), JwtMintAuth
               (Kling: a locally-signed HS256 JWT, cached until near expiry), and GoogleSaAuth
               (Agent Platform / Vertex: an RS256 service-account JWT exchanged at the token
               endpoint for a Bearer access token, cached until expiry). A credential never appears
               in the wrong request's headers, in an error, or in a log.
  * _http.py — request(): apply auth, queue behind the per-provider rate limiter, retry on 429 with
               the Retry-After penalty, and raise AdapterError on other non-2xx with a HYGIENIC
               message (provider + method + path only — never a query string, an auth header value,
               or a full body). parse_json(): defensive parsing that raises AdapterError.
  * _ratelimit.py — H8: reconfiguring a provider mid-use is refused (the live-semaphore bug).

The generic submit->poll->download loop is authored in P-4a with the first async adapter using it.
Everything here runs against httpx2.MockTransport / an in-test RateLimiter — no live network.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import httpx2
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256
from sfvf._ratelimit import RateLimiter
from sfvf.providers._auth import BearerAuth, GoogleSaAuth, HeaderAuth, JwtMintAuth
from sfvf.providers._http import parse_json, request
from sfvf.providers.base import AdapterError, Cost


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _jwt_parts(token: str) -> tuple[dict, dict, bytes, str]:
    header_b64, payload_b64, sig_b64 = token.split(".")
    header = json.loads(_b64url_decode(header_b64))
    payload = json.loads(_b64url_decode(payload_b64))
    return header, payload, _b64url_decode(sig_b64), f"{header_b64}.{payload_b64}"


class _Clock:
    """A movable clock so token expiry/caching is deterministic."""

    def __init__(self, now: float = 1_000_000.0) -> None:
        self.t = now

    def __call__(self) -> float:
        return self.t


# ---------------------------------------------------------------------------
# base.py — AdapterError + Cost
# ---------------------------------------------------------------------------


def test_adapter_error_is_a_runtime_error() -> None:
    assert issubclass(AdapterError, RuntimeError)


def test_cost_carries_amount_and_a_source_label() -> None:
    cost = Cost(amount=0.042, source="metered")
    assert cost.amount == 0.042
    assert cost.source in {"reported", "metered", "priced"}
    assert cost.source == "metered"


# ---------------------------------------------------------------------------
# _auth.py — the static strategies
# ---------------------------------------------------------------------------


def test_bearer_auth_sets_the_authorization_header() -> None:
    assert BearerAuth("tok-123").headers() == {"Authorization": "Bearer tok-123"}


def test_header_auth_sets_an_arbitrary_named_header() -> None:
    # Used for BFL's x-key / Google's x-goog-api-key: the credential is a header VALUE, not a query.
    assert HeaderAuth("x-key", "secret-key").headers() == {"x-key": "secret-key"}


# ---------------------------------------------------------------------------
# _auth.py — JwtMintAuth (Kling: local HS256, no network)
# ---------------------------------------------------------------------------


def test_jwt_mint_auth_signs_a_valid_hs256_token_with_the_expected_claims() -> None:
    clock = _Clock()
    auth = JwtMintAuth("access-key", "secret-key", ttl_s=1800, now=clock)
    token = auth.headers()["Authorization"].removeprefix("Bearer ")

    header, payload, signature, signing_input = _jwt_parts(token)
    assert header["alg"] == "HS256"
    assert payload["iss"] == "access-key"
    assert payload["exp"] == pytest.approx(clock.t + 1800, abs=2)
    # The signature verifies under the secret key (a real HS256 JWT, not a stub string).
    expected = hmac.new(b"secret-key", signing_input.encode(), hashlib.sha256).digest()
    assert hmac.compare_digest(signature, expected)


def test_jwt_mint_auth_caches_within_ttl_and_remints_after_expiry() -> None:
    clock = _Clock()
    auth = JwtMintAuth("access-key", "secret-key", ttl_s=1800, now=clock)
    first = auth.headers()["Authorization"]
    clock.t += 60  # still well within the 30-min TTL
    assert auth.headers()["Authorization"] == first  # reused, not re-minted every call
    clock.t += 1800  # now past expiry
    assert auth.headers()["Authorization"] != first  # re-minted


def test_jwt_mint_auth_never_leaks_the_secret_key_in_its_output() -> None:
    auth = JwtMintAuth("access-key", "secret-key", ttl_s=1800, now=_Clock())
    assert "secret-key" not in auth.headers()["Authorization"]


# ---------------------------------------------------------------------------
# _auth.py — GoogleSaAuth (Agent Platform / Vertex: RS256 SA-JWT -> token exchange)
# ---------------------------------------------------------------------------


def _service_account() -> tuple[dict, rsa.RSAPublicKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    sa = {
        "client_email": "svc@proj.iam.gserviceaccount.com",
        "private_key": pem,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    return sa, key.public_key()


def _token_transport(
    seen: list[httpx2.Request], *, value: str = "ya29.mock"
) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"access_token": value, "expires_in": 3600})

    return httpx2.MockTransport(handler)


def test_google_sa_auth_exchanges_a_signed_assertion_for_a_bearer_token() -> None:
    sa, public_key = _service_account()
    seen: list[httpx2.Request] = []
    auth = GoogleSaAuth(sa, transport=_token_transport(seen), now=_Clock())

    assert auth.headers() == {"Authorization": "Bearer ya29.mock"}

    assert len(seen) == 1
    exchange = seen[0]
    assert str(exchange.url) == sa["token_uri"]
    body = exchange.read().decode()
    assert "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer" in body
    # The assertion is a real RS256 JWT signed by the SA private key, aimed at the token endpoint.
    assertion = _assertion_from_body(body)
    header, payload, signature, signing_input = _jwt_parts(assertion)
    assert header["alg"] == "RS256"
    assert payload["iss"] == sa["client_email"]
    assert payload["aud"] == sa["token_uri"]
    public_key.verify(signature, signing_input.encode(), padding.PKCS1v15(), SHA256())


def test_google_sa_auth_caches_the_access_token_until_expiry() -> None:
    sa, _ = _service_account()
    seen: list[httpx2.Request] = []
    clock = _Clock()
    auth = GoogleSaAuth(sa, transport=_token_transport(seen), now=clock)
    auth.headers()
    clock.t += 60
    auth.headers()
    assert len(seen) == 1  # cached: no second exchange within the token's lifetime
    clock.t += 3600
    auth.headers()
    assert len(seen) == 2  # re-exchanged after expiry


def test_google_sa_auth_never_leaks_the_private_key() -> None:
    sa, _ = _service_account()
    auth = GoogleSaAuth(sa, transport=_token_transport([]), now=_Clock())
    assert sa["private_key"] not in json.dumps(auth.headers())


def test_google_sa_auth_raises_a_hygienic_adapter_error_on_a_failed_exchange() -> None:
    sa, _ = _service_account()

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, json={"error": "invalid_grant"})

    auth = GoogleSaAuth(sa, transport=httpx2.MockTransport(handler), now=_Clock())
    with pytest.raises(AdapterError) as exc:
        auth.headers()
    message = str(exc.value)
    assert "google" in message.lower()
    assert sa["private_key"] not in message  # the signed assertion / key never reaches the error


def _assertion_from_body(body: str) -> str:
    for pair in body.split("&"):
        if pair.startswith("assertion="):
            from urllib.parse import unquote

            return unquote(pair.removeprefix("assertion="))
    raise AssertionError("no assertion field in the token-exchange body")


# ---------------------------------------------------------------------------
# _http.py — request(): auth application, 429 retry, error hygiene
# ---------------------------------------------------------------------------

_SECRET = "super-secret-token"


def _client(handler) -> httpx2.Client:
    return httpx2.Client(base_url="https://api.acme.test", transport=httpx2.MockTransport(handler))


def _idle_limiter() -> RateLimiter:
    # A real limiter whose sleep is a no-op, so paced/penalty waits do not slow the test.
    return RateLimiter(sleep=lambda _s: None)


def test_request_applies_auth_and_returns_on_success() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"ok": True})

    resp = request(
        _client(handler),
        "POST",
        "/generate",
        provider="acme",
        auth=BearerAuth(_SECRET),
        limiter=_idle_limiter(),
        json={"prompt": "hi"},
    )
    assert resp.status_code == 200
    assert seen[0].headers.get("authorization") == f"Bearer {_SECRET}"


def test_request_retries_on_429_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(429, headers={"Retry-After": "0"}, json={"e": "rate"})
        return httpx2.Response(200, json={"ok": True})

    resp = request(
        _client(handler),
        "POST",
        "/generate",
        provider="acme",
        auth=BearerAuth(_SECRET),
        limiter=_idle_limiter(),
    )
    assert resp.status_code == 200
    assert calls["n"] == 2  # retried exactly once after the 429


def test_request_gives_up_after_max_attempts_of_429() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429, headers={"Retry-After": "0"}, json={"e": "rate"})

    with pytest.raises(AdapterError):
        request(
            _client(handler),
            "POST",
            "/generate",
            provider="acme",
            auth=BearerAuth(_SECRET),
            limiter=_idle_limiter(),
            max_attempts=3,
        )


def test_request_raises_a_hygienic_error_on_non_2xx() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, text="internal error detail")

    with pytest.raises(AdapterError) as exc:
        request(
            _client(handler),
            "POST",
            "/generate?key=SHOULD_NOT_APPEAR",
            provider="acme",
            auth=BearerAuth(_SECRET),
            limiter=_idle_limiter(),
        )
    message = str(exc.value)
    assert "acme" in message
    assert "/generate" in message  # names where it failed
    assert "500" in message
    assert _SECRET not in message  # no auth header value
    assert "SHOULD_NOT_APPEAR" not in message  # no query string


def test_parse_json_raises_adapter_error_on_a_non_object_body() -> None:
    resp = httpx2.Response(200, text="<html>not json</html>")
    with pytest.raises(AdapterError):
        parse_json(resp, provider="acme", where="submit")


def test_parse_json_returns_the_object_on_success() -> None:
    resp = httpx2.Response(200, json={"request_id": "r1"})
    assert parse_json(resp, provider="acme", where="submit") == {"request_id": "r1"}


# ---------------------------------------------------------------------------
# _ratelimit.py — H8: no live-semaphore replacement while a slot is held
# ---------------------------------------------------------------------------


def test_configure_before_first_use_is_allowed() -> None:
    rl = RateLimiter(sleep=lambda _s: None)
    rl.configure("acme", max_concurrency=1)
    rl.configure("acme", max_concurrency=3)  # still before any slot is taken: fine


def test_reconfigure_while_a_slot_is_held_is_refused() -> None:
    rl = RateLimiter(sleep=lambda _s: None)
    rl.configure("acme", max_concurrency=2)
    with rl.slot("acme"), pytest.raises(RuntimeError):
        rl.configure("acme", max_concurrency=5)  # would replace a live semaphore (H8)
