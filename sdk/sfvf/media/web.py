from __future__ import annotations

import hashlib
import ipaddress
import socket
from typing import Any, TypedDict
from urllib.parse import urljoin, urlsplit

from .._ffmpeg import solid_image
from .._runtime import current_context
from .graphics import _artifact, _sha8

# default vision model for check_relevance (revisited at increment 4)
_VISION_MODEL = "openai/gpt-4o"
_STUB_POOL = 256  # dry-run search returns up to this many deterministic candidates
_MAX_CONSIDER = 50
_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # 25 MiB
_MAX_REDIRECTS = 3
_DL_CHUNK = 65536
_NAT64_NET = ipaddress.ip_network("64:ff9b::/96")
_V4COMPAT_NET = ipaddress.ip_network("::/96")
_6TO4_NET = ipaddress.ip_network("2002::/16")
_TEREDO_NET = ipaddress.ip_network("2001::/32")
_NAT64_LOCAL_NET = ipaddress.ip_network("64:ff9b:1::/48")


def _resolve(host: str) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, None)]


def _client() -> Any:
    import httpx2

    # trust_env=False disables env proxies (HTTP(S)_PROXY); redirects handled manually.
    return httpx2.Client(trust_env=False, follow_redirects=False, timeout=30.0)


def _public_addr(ip: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError as exc:  # scoped/zoned/malformed -> reject, clean message
        raise ValueError(f"fetch: unparseable resolved address {ip!r}") from exc
    if isinstance(addr, ipaddress.IPv6Address):
        if (
            addr in _TEREDO_NET
            or addr in _NAT64_LOCAL_NET
            or addr.is_site_local
            or addr.is_reserved
        ):
            raise ValueError(f"fetch: non-public address {ip}")
        embedded = addr.ipv4_mapped
        if embedded is None and (addr in _NAT64_NET or addr in _V4COMPAT_NET):
            embedded = ipaddress.IPv4Address(addr.packed[-4:])
        if embedded is None and addr in _6TO4_NET:
            embedded = ipaddress.IPv4Address(addr.packed[2:6])
        if embedded is not None:
            addr = embedded
    return addr


def _validated_pin_ip(host: str) -> str:
    try:
        ips = _resolve(host)
    except OSError as exc:
        raise ValueError(f"fetch: cannot resolve host {host!r}") from exc
    if not ips:
        raise ValueError(f"fetch: cannot resolve host {host!r}")
    for ip in ips:
        addr = _public_addr(ip)
        if not addr.is_global or addr.is_multicast:
            raise ValueError(f"fetch: host {host!r} resolves to a non-public address {ip}")
    return ips[0]


def _content_hash(data: bytes) -> str:
    # 64-bit content hash (inc3b commitment, done here)
    return hashlib.sha256(data).hexdigest()[:16]


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
        hostpart = f"[{ip}]" if ":" in ip else ip
        pinned = f"https://{hostpart}:{port}{parts.path or '/'}"
        if parts.query:
            pinned = f"{pinned}?{parts.query}"
        with (
            _client() as client,
            client.stream(
                "GET", pinned, headers={"Host": parts.netloc}, extensions={"sni_hostname": host}
            ) as resp,
        ):
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                if not loc:
                    raise ValueError("fetch: redirect without a location")
                url = urljoin(url, loc)  # re-validate the next hop on the next loop
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


class ImageCandidate(TypedDict):
    source: str
    url: str
    thumbnail: str
    licence: str
    attribution: str
    width: int
    height: int
    title: str
    rank: int


class Relevance(TypedDict):
    relevant: bool
    score: float
    reason: str


class SourcedImage(TypedDict):
    path: str
    candidate: ImageCandidate
    relevance: Relevance


def search(
    query: str,
    *,
    sources: tuple[str, ...] = ("commons",),
    limit: int = 10,
    licence: str | None = None,
) -> list[ImageCandidate]:
    ctx = current_context()
    if not sources or any(s not in ("commons", "web") for s in sources):
        raise ValueError(
            f"sources must be a non-empty subset of ('commons','web'); got {sources!r}"
        )
    if ctx.dry_run:
        n = max(0, min(limit, _STUB_POOL))
        candidates: list[ImageCandidate] = []
        for i in range(n):
            tier = sources[i % len(sources)]
            licence = "unknown" if tier == "web" else "CC0-1.0"
            candidates.append(
                ImageCandidate(
                    source=tier,
                    url=f"https://example.invalid/{_sha8(['web.search', query, i])}.jpg",
                    thumbnail=f"https://example.invalid/{_sha8(['web.thumb', query, i])}-t.jpg",
                    licence=licence,
                    attribution="dry-run stub",
                    width=800,
                    height=600,
                    title=f"{query} — stub {i}",
                    rank=i,
                )
            )
        return candidates
    import importlib

    from ..providers.registry import PROVIDERS

    if "web" in sources:
        raise NotImplementedError("media.web.search web tier is built in increment 6")

    out: list[ImageCandidate] = []
    for tier in sources:
        if tier == "commons":
            provider = PROVIDERS["openverse"]
            secrets = {name: ctx.secret(name) for name in provider.secret_names}  # {} — keyless
            adapter = importlib.import_module(f"sfvf.providers.{provider.adapter}")
            out.extend(
                adapter.search(
                    query, limit=limit, licence=licence, provider=provider, secrets=secrets
                )
            )
        else:  # "web"
            raise NotImplementedError("media.web.search web tier is built in increment 6")
    # URL-deduplicate across tiers, preserving first-seen order (design §3.1).
    seen: set[str] = set()
    deduped: list[ImageCandidate] = []
    for c in out:
        if c["url"] not in seen:
            seen.add(c["url"])
            deduped.append(c)
    return deduped


def fetch(candidate: ImageCandidate) -> str:
    ctx = current_context()
    if ctx.dry_run:
        stem = _sha8(["web.fetch", candidate["url"]])
        dest, rel = _artifact(ctx, f"web-{stem}.png")
        solid_image(dest, width=64, height=64)
        # valid PNGs ignore bytes after IEND; append the full stem so the stub is byte-distinct per
        # candidate (a dry-run content-addressed intake keeps distinct candidates distinct)
        with dest.open("ab") as fh:
            fh.write(b"\nweb-stub:" + stem.encode())
        return rel
    data = _download_guarded(candidate["url"])
    stem = _content_hash(data)
    dest, rel = _artifact(ctx, f"web-{stem}.bin")  # raw bytes; 3b re-encodes to a real ext
    dest.write_bytes(data)
    return rel


def check_relevance(image: str, *, subject: str, model: str = _VISION_MODEL) -> Relevance:
    ctx = current_context()
    if ctx.dry_run:
        return Relevance(relevant=True, score=1.0, reason="dry-run stub")
    raise NotImplementedError(
        "media.web.check_relevance real path is built in increment 4 (VLM gate)"
    )


def source(
    query: str,
    *,
    subject: str,
    sources: tuple[str, ...] = ("commons",),
    want: int = 1,
    consider: int = 8,
    min_score: float = 0.6,
    licence: str | None = None,
) -> list[SourcedImage]:
    ctx = current_context()
    if consider > _MAX_CONSIDER:
        raise ValueError(f"consider={consider} exceeds the fan-out ceiling {_MAX_CONSIDER}")
    if ctx.dry_run:
        n = max(0, want)  # clamp — no negative-slice leakage
        candidates = search(query, sources=sources, limit=consider, licence=licence)[:n]
        return [
            SourcedImage(
                path=fetch(c),
                candidate=c,
                relevance=Relevance(relevant=True, score=1.0, reason="dry-run stub"),
            )
            for c in candidates
        ]
    raise NotImplementedError("media.web.source real path is built in increment 5")
