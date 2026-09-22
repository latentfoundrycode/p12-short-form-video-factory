from __future__ import annotations

import hashlib
import io
import ipaddress
import socket
from typing import Any, TypedDict, cast
from urllib.parse import urljoin, urlsplit

from .._ffmpeg import solid_image
from .._runtime import current_context
from .graphics import _artifact, _sha8

# default vision model for check_relevance (revisited at increment 4)
_VISION_MODEL = "openai/gpt-4o"
_STUB_POOL = 256  # dry-run search returns up to this many deterministic candidates
_MAX_CONSIDER = 50
_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # 25 MiB
_MAX_IMAGE_PIXELS = 40_000_000
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


def _normalise_image(data: bytes) -> tuple[bytes, str]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        sniffed = "png"
    elif data.startswith(b"\xff\xd8\xff"):
        sniffed = "jpeg"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        sniffed = "gif"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        sniffed = "webp"
    else:
        raise ValueError("unsupported image type")

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "media.web requires the 'Pillow' package. Install the SDK "
            "'web' extra: pip install 'sfvf[web]'."
        ) from exc

    expected = {"png": "PNG", "jpeg": "JPEG", "gif": "GIF", "webp": "WEBP"}[sniffed]
    Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS
    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > _MAX_IMAGE_PIXELS:
            raise ValueError("image exceeds the pixel cap")
        if img.format != expected:
            raise ValueError("image format does not match magic bytes")
        if getattr(img, "n_frames", 1) > 1 or getattr(img, "is_animated", False):
            raise ValueError("animated images are not allowed")
        has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
        if sniffed == "jpeg":
            out = img.convert("RGB")
            out.info.clear()
            buf = io.BytesIO()
            out.save(buf, format="JPEG", quality=90, exif=b"")
            return buf.getvalue(), "jpg"
        mode = "RGBA" if has_alpha else "RGB"
        out = img.convert(mode)
        out.info.clear()
        buf = io.BytesIO()
        if sniffed == "webp":
            out.save(buf, format="WEBP")
            return buf.getvalue(), "webp"
        out.save(buf, format="PNG")
        return buf.getvalue(), "png"
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"unreadable image: {exc}") from exc


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
                "GET",
                pinned,
                headers={"Host": parts.netloc, "Accept-Encoding": "identity"},
                extensions={"sni_hostname": host},
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
            encoding = resp.headers.get("content-encoding")
            if encoding is not None and not all(
                t.strip().lower() == "identity" for t in encoding.split(",")
            ):
                raise ValueError(f"fetch: unexpected content-encoding {encoding}")
            buf = bytearray()
            # Accept-Encoding: identity + the content-encoding reject above guarantee no decoder
            # runs, so iter_bytes cannot decompress here — it caps the actual (identity) bytes.
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
        else:  # "web" — PAID tier; the serpapi adapter owns the budget reserve/reconcile
            provider = PROVIDERS["serpapi"]
            secrets = {name: ctx.secret(name) for name in provider.secret_names}
            adapter = importlib.import_module(f"sfvf.providers.{provider.adapter}")
            out.extend(
                adapter.search(
                    query, limit=limit, licence=licence, provider=provider, secrets=secrets
                )
            )
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
    canonical, ext = _normalise_image(data)
    stem = _content_hash(canonical)
    dest, rel = _artifact(ctx, f"web-{stem}.{ext}")
    dest.write_bytes(canonical)
    return rel


def check_relevance(image: str, *, subject: str, model: str = _VISION_MODEL) -> Relevance:
    ctx = current_context()
    if ctx.dry_run:
        return Relevance(relevant=True, score=1.0, reason="dry-run stub")
    from sfvf import agents

    schema = {
        "type": "object",
        "properties": {
            "relevant": {"type": "boolean"},
            "score": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": ["relevant", "score", "reason"],
        "additionalProperties": False,
    }
    prompt = (
        f"Assess whether this image depicts the following subject.\nSubject: {subject}\nReturn "
        "relevant (does it depict the subject), score (0.0-1.0 confidence it matches), "
        "and a brief reason."
    )
    result = cast(
        dict[str, Any],
        agents.llm(prompt, agent="image-relevance", model=model, attach=[image], schema=schema),
    )
    score = min(1.0, max(0.0, float(result["score"])))
    return Relevance(
        relevant=bool(result["relevant"]),
        score=score,
        reason=str(result["reason"]),
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
    n = max(0, want)  # clamp: no negative-slice leakage
    results: list[SourcedImage] = []
    if n == 0:
        return results
    candidates = search(query, sources=sources, limit=consider, licence=licence)
    for c in candidates:  # search-provider RANK ORDER; `search` already bounds to `consider`
        with ctx.step(
            "web.source",
            # the cached verdict depends on the vision model too — include it so a
            # _VISION_MODEL change invalidates the entry (cache versioning keys on
            # the workflow version, not the SDK revision)
            inputs={"url": c["url"], "subject": subject, "model": _VISION_MODEL},
            label=f"web.source:{c['url']}",
            paid=True,  # includes a paid VLM check -> PAID cache partition (resume doesn't repay)
        ) as step:
            if not step.cached:
                path = fetch(c)
                relevance = check_relevance(path, subject=subject, model=_VISION_MODEL)
                step.set({"path": path, "relevance": relevance})
            entry = step.value
        relevance = entry["relevance"]
        if relevance["score"] >= min_score:
            results.append(SourcedImage(path=entry["path"], candidate=c, relevance=relevance))
            if len(results) >= n:
                break
    return results
