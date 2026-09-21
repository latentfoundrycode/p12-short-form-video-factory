# TASK — web-image-sourcing increment 3a: SSRF-hardened `media.web.fetch` download

Frozen RED contract: `tests/integration/test_media_web_fetch.py`. Design: `docs/DESIGN-web-image-sourcing.md`
§7.1 (SSRF guard) + §7.2 (byte cap; the wider content hash — do it HERE). Scope: `sdk/sfvf/media/web.py` ONLY.

Build `fetch`'s REAL (non-dry-run) path as an SSRF-guarded download. The dry-run branch stays unchanged.
Add module-level seams/constants and the guarded download. httpx2 is httpx-like (2.12); `ipaddress.is_global`
+ the `sni_hostname` request extension are verified to work.

## Constants + seams (module level, patchable — the tests monkeypatch them)
```python
import hashlib
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024   # 25 MiB
_MAX_REDIRECTS = 3
_DL_CHUNK = 65536


def _resolve(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _client() -> Any:
    import httpx2
    # trust_env=False disables env proxies (HTTP(S)_PROXY); redirects handled manually.
    return httpx2.Client(trust_env=False, follow_redirects=False, timeout=30.0)


def _validated_pin_ip(host: str) -> str:
    ips = _resolve(host)
    if not ips:
        raise ValueError(f"fetch: cannot resolve host {host!r}")
    for ip in ips:                                   # EVERY resolved IP must be public
        addr = ipaddress.ip_address(ip)
        if getattr(addr, "ipv4_mapped", None):
            addr = addr.ipv4_mapped
        if not addr.is_global or addr.is_multicast:
            raise ValueError(f"fetch: host {host!r} resolves to a non-public address {ip}")
    return ips[0]                                    # pin the first (all are validated)


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]     # 64-bit content hash (inc3b commitment, done here)


def _download_guarded(url: str) -> bytes:
    for _ in range(_MAX_REDIRECTS + 1):
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise ValueError("fetch: only https URLs are allowed")
        host = parts.hostname
        if not host:
            raise ValueError("fetch: URL has no host")
        ip = _validated_pin_ip(host)
        port = parts.port or 443
        pinned = f"https://{ip}:{port}{parts.path or '/'}"
        if parts.query:
            pinned = f"{pinned}?{parts.query}"
        with _client() as client:
            with client.stream(
                "GET", pinned, headers={"Host": parts.netloc}, extensions={"sni_hostname": host}
            ) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location")
                    if not loc:
                        raise ValueError("fetch: redirect without a location")
                    url = urljoin(url, loc)          # re-validate the next hop on the next loop
                    continue
                if resp.status_code != 200:
                    raise ValueError(f"fetch: HTTP {resp.status_code}")
                buf = bytearray()
                for chunk in resp.iter_bytes(_DL_CHUNK):
                    buf += chunk
                    if len(buf) > _MAX_DOWNLOAD_BYTES:
                        raise ValueError("fetch: download exceeds the byte cap")
                return bytes(buf)
    raise ValueError("fetch: too many redirects")
```

## `fetch`'s real path
Replace the `raise NotImplementedError(...)` in `fetch` (after the dry-run branch) with:
```python
    data = _download_guarded(candidate["url"])
    stem = _content_hash(data)
    dest, rel = _artifact(ctx, f"web-{stem}.bin")   # raw bytes; 3b validates type + re-encodes to a real ext
    dest.write_bytes(data)
    return rel
```
(`_artifact` and `current_context` are already imported/used in this module.)

## Notes
- Do NOT change `search`, `check_relevance`, `source`, or the `fetch` dry-run stub.
- `_content_hash` is `sha256[:16]` (64-bit) — this satisfies the increment-3b binding commitment to widen
  the real fetch hash beyond the 32-bit `_sha8`; it lives here because 3a writes the file.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_fetch.py tests/integration/test_media_web_surface.py tests/integration/test_media_web_commons.py -q` — all pass.
- `ruff check` + `ruff format --check` + `mypy` clean on `sdk/sfvf/media/web.py`.
- `git diff` shows exactly `sdk/sfvf/media/web.py`.

## Round 2 (resolve hygiene)
An unresolvable / malformed host currently lets `socket.getaddrinfo` raise a raw `socket.gaierror`
out of `fetch`. Wrap the resolve in `_validated_pin_ip` so a resolution failure is a clean
`ValueError` (an untrusted URL must not leak a low-level OSError):
```python
def _validated_pin_ip(host: str) -> str:
    try:
        ips = _resolve(host)
    except OSError as exc:
        raise ValueError(f"fetch: cannot resolve host {host!r}") from exc
    if not ips:
        raise ValueError(f"fetch: cannot resolve host {host!r}")
    ... (rest unchanged)
```
Frozen test: `test_fetch_raises_valueerror_when_the_host_cannot_be_resolved`.
