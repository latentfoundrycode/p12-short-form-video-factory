"""Authentication strategies shared by provider adapters."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Any


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _json_segment(value: dict[str, Any]) -> str:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return _b64url(raw)


class BearerAuth:
    def __init__(self, token: str) -> None:
        self._token = token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}


class HeaderAuth:
    def __init__(self, name: str, value: str) -> None:
        self._name = name
        self._value = value

    def headers(self) -> dict[str, str]:
        return {self._name: self._value}


class JwtMintAuth:
    def __init__(
        self,
        access_key: str,
        secret_key: str,
        *,
        ttl_s: int = 1800,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._access_key = access_key
        self._secret_key = secret_key
        self._ttl_s = ttl_s
        self._now = now
        self._cached_token: str | None = None
        self._cached_exp = 0.0

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    def _token(self) -> str:
        now = self._now()
        if self._cached_token is not None and now < self._cached_exp:
            return self._cached_token

        issued_at = int(now)
        header = _json_segment({"alg": "HS256", "typ": "JWT"})
        payload = _json_segment(
            {
                "exp": issued_at + self._ttl_s,
                "iss": self._access_key,
                "nbf": issued_at,
            }
        )
        signing_input = f"{header}.{payload}"
        signature = hmac.new(
            self._secret_key.encode(),
            signing_input.encode(),
            hashlib.sha256,
        ).digest()
        self._cached_token = f"{signing_input}.{_b64url(signature)}"
        self._cached_exp = issued_at + self._ttl_s
        return self._cached_token


class GoogleSaAuth:
    def __init__(
        self,
        sa: dict[str, Any],
        *,
        scope: str = "https://www.googleapis.com/auth/cloud-platform",
        transport: Any | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._sa = sa
        self._scope = scope
        self._transport = transport
        self._now = now
        self._cached_token: str | None = None
        self._cached_exp = 0.0

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token()}"}

    def _access_token(self) -> str:
        now = self._now()
        if self._cached_token is not None and now < self._cached_exp:
            return self._cached_token

        try:
            import httpx2
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError as exc:
            raise RuntimeError(
                "GoogleSaAuth requires the 'cryptography' and 'httpx2' packages"
            ) from exc

        issued_at = int(now)
        header = _json_segment({"alg": "RS256", "typ": "JWT"})
        payload = _json_segment(
            {
                "aud": self._sa["token_uri"],
                "exp": issued_at + 3600,
                "iat": issued_at,
                "iss": self._sa["client_email"],
                "scope": self._scope,
            }
        )
        signing_input = f"{header}.{payload}"
        private_key: Any = serialization.load_pem_private_key(
            self._sa["private_key"].encode(),
            password=None,
        )
        signature = private_key.sign(
            signing_input.encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        assertion = f"{signing_input}.{_b64url(signature)}"

        with httpx2.Client(transport=self._transport) as client:
            response = client.post(
                self._sa["token_uri"],
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )

        if not 200 <= response.status_code < 300:
            from .base import AdapterError

            raise AdapterError(
                "google",
                status=response.status_code,
                where="token exchange",
                detail="token exchange failed",
            )

        data = response.json()
        try:
            access_token = data["access_token"]
            expires_in = float(data["expires_in"])
            if not isinstance(access_token, str):
                raise TypeError
        except (KeyError, TypeError, ValueError) as exc:
            from .base import AdapterError

            raise AdapterError(
                "google",
                status=response.status_code,
                where="token exchange",
                detail="invalid token response",
            ) from exc

        self._cached_token = access_token
        self._cached_exp = now + expires_in
        return access_token
