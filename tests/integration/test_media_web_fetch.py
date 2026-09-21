"""Frozen contract — web-image-sourcing increment 3a: SSRF-hardened `media.web.fetch` download.

`fetch(candidate)` downloads the candidate's image URL into the run workspace, but the URL and
bytes are UNTRUSTED (from a web search). Per docs/DESIGN §7.1 the download is guarded: https-only;
the host is resolved and EVERY resolved IP must be globally-routable unicast (private / loopback /
link-local / CGNAT / ULA / multicast / reserved / IPv4-mapped rejected); the connection is PINNED to
the validated IP (TLS SNI + cert verification still against the real hostname, defeating DNS
rebinding); environment proxies are disabled; redirects are NOT auto-followed (each hop is
re-validated); and the body is byte-capped.

No real network: `media.web._resolve` (host -> list[ip]) and `media.web._client` (-> httpx2.Client)
are the patched seams. The byte pipeline (magic-byte type gate, pixel-bomb bound, re-encode) is
increment 3b; increment 3a is the SAFE DOWNLOAD + SSRF guard + byte cap only.
"""

import gzip
import io
import ipaddress
import struct
import zlib
from pathlib import Path

import httpx2
import pytest
from PIL import Image
from sfvf import media
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths
from sfvf.media import web as web_mod

_PUBLIC_IP = "93.184.216.34"


def _ctx(tmp: Path) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=False,
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
        )
    )


def _run(ctx: Context, fn):
    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def _candidate(url: str) -> dict:
    return {
        "source": "commons",
        "url": url,
        "thumbnail": "",
        "licence": "cc0 1.0",
        "attribution": "x",
        "width": 8,
        "height": 8,
        "title": "t",
        "rank": 0,
    }


def _png_bytes(n: int = 8) -> bytes:
    # a tiny valid PNG (n x n solid), constructed with stdlib so the mock returns real image bytes
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * n for _ in range(n))
    comp = zlib.compress(raw)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", comp) + chunk(b"IEND", b"")


def _install(monkeypatch: pytest.MonkeyPatch, handler, *, resolve_to=_PUBLIC_IP) -> list:
    """Patch the resolver (host -> [ip]) and the client transport; return the recorded requests."""
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request, len(seen))

    def _client() -> httpx2.Client:
        # trust_env False (no env proxies); redirects not auto-followed (asserted via behaviour).
        return httpx2.Client(
            transport=httpx2.MockTransport(wrapped), trust_env=False, follow_redirects=False
        )

    ips = resolve_to if isinstance(resolve_to, list) else [resolve_to]
    monkeypatch.setattr(web_mod, "_resolve", lambda host: list(ips))
    monkeypatch.setattr(web_mod, "_client", _client)
    return seen


def _ok(_request: httpx2.Request, _n: int) -> httpx2.Response:
    return httpx2.Response(200, content=_png_bytes(), headers={"content-type": "image/png"})


# --- happy path: pin the validated public IP, write the file ------------------------------------


def test_fetch_pins_the_validated_public_ip_and_writes_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install(monkeypatch, _ok, resolve_to=_PUBLIC_IP)
    rel = _run(
        _ctx(tmp_path), lambda: media.web.fetch(_candidate("https://images.example.com/a.png"))
    )
    assert isinstance(rel, str) and not Path(rel).is_absolute()
    target = tmp_path / rel
    # increment 3b: fetch writes the NORMALISED (decoded+re-encoded) image and discards the
    # original download, so the file is a valid image of the right size named with a real image
    # extension — not the raw downloaded bytes.
    assert target.is_file() and rel.endswith(".png")
    out = Image.open(io.BytesIO(target.read_bytes()))
    assert out.format == "PNG" and out.size == (8, 8)
    # pinned to the RESOLVED-and-validated IP, but TLS/Host stay the real hostname
    assert len(seen) == 1
    req = seen[0]
    assert req.url.host == _PUBLIC_IP, (
        "must connect to the validated IP, not re-resolve the hostname"
    )
    assert req.headers.get("host", "").startswith("images.example.com")
    assert req.extensions.get("sni_hostname") == "images.example.com"


# --- SSRF guard: reject non-https and non-global resolved IPs ------------------------------------


def test_fetch_raises_valueerror_when_the_host_cannot_be_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An unresolvable / malformed host must fail as a clean ValueError, not a raw socket.gaierror
    # (an untrusted URL should never leak a low-level OSError out of fetch).
    import socket

    seen = _install(monkeypatch, _ok)

    def boom(_host: str):
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(web_mod, "_resolve", boom)
    with pytest.raises(ValueError):
        _run(
            _ctx(tmp_path),
            lambda: media.web.fetch(_candidate("https://nope.example.invalid/a.png")),
        )
    assert seen == []


def test_fetch_requires_https_before_any_resolve_or_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install(monkeypatch, _ok)

    def boom(_host: str):
        raise AssertionError("must not resolve a non-https url")

    monkeypatch.setattr(web_mod, "_resolve", boom)
    with pytest.raises(ValueError):
        _run(_ctx(tmp_path), lambda: media.web.fetch(_candidate("http://images.example.com/a.png")))
    assert seen == []


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.5",
        "169.254.1.1",
        "100.64.0.1",
        "::1",
        "fc00::1",
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        # IPv6 forms that EMBED a private/internal IPv4 but Python's is_global returns True —
        # unwrap and reject on the embedded address (security-auditor found this as a real bypass):
        "64:ff9b::a00:1",  # NAT64 (64:ff9b::/96) -> 10.0.0.1
        "64:ff9b::a9fe:a9fe",  # NAT64 -> 169.254.169.254 (cloud metadata)
        "::7f00:1",  # IPv4-compatible (::/96) -> 127.0.0.1
        "::127.0.0.1",  # IPv4-compatible -> 127.0.0.1
        "fe80::1%eth0",  # scoped/zoned literal -> reject (fail closed, clean ValueError)
        # IPv6 transition/reserved forms that must be rejected VERSION-INDEPENDENTLY, not by
        # relying on `is_global` (CPython 3.12.0-3.12.3 misclassify several of these, and a
        # cached workflow venv can run new fetch code on such an interpreter — Review B, PR #142).
        "fec0::c0a8:101",  # deprecated site-local (fec0::/10) -> is_global=True on CPython; reject
        "fec0::1",  # site-local
        "2002:0a00:0001::",  # 6to4 (2002::/16) embedding 10.0.0.1 -> unwrap+reject
        "2002:7f00:0001::",  # 6to4 embedding 127.0.0.1
        "2002:a9fe:a9fe::",  # 6to4 embedding 169.254.169.254 (cloud metadata)
        "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # Teredo (2001::/32) -> reject the range
        "64:ff9b:1::a9fe:a9fe",  # RFC 8215 local-use NAT64 (64:ff9b:1::/48) -> reject the range
        "0100::1",  # discard-only / reserved -> reject
    ],
)
def test_fetch_rejects_a_non_global_resolved_ip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ip: str
) -> None:
    seen = _install(monkeypatch, _ok, resolve_to=ip)
    with pytest.raises(ValueError):
        _run(_ctx(tmp_path), lambda: media.web.fetch(_candidate("https://evil.example.com/a.png")))
    assert seen == [], "a non-global resolved IP must be rejected before any request"


@pytest.mark.parametrize(
    "sixtofour,embedded",
    [
        ("2002:0a00:0001::", "10.0.0.1"),
        ("2002:7f00:0001::", "127.0.0.1"),
        ("2002:a9fe:a9fe::", "169.254.169.254"),  # cloud metadata via 6to4
    ],
)
def test_public_addr_unwraps_6to4_to_the_embedded_ipv4(sixtofour: str, embedded: str) -> None:
    # 6to4 (2002::/16) embeds an IPv4 at bytes 2-6. `_public_addr` must unwrap it so the
    # embedded (here private) address is what gets validated by `_validated_pin_ip` — a
    # VERSION-INDEPENDENT guard that does not lean on the interpreter's `is_global` table
    # (CPython 3.12.0-3.12.3 misclassify these as global). This is the mechanism assertion:
    # it is RED on every interpreter until the unwrap is added, whereas an outcome-only
    # reject test passes trivially on 3.12.4+ where `is_global` already returns False.
    assert web_mod._public_addr(sixtofour) == ipaddress.ip_address(embedded)


def test_fetch_pins_and_brackets_a_public_ipv6(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A legitimately public IPv6 must work (and the pinned URL must bracket the literal, else httpx
    # raises InvalidURL). Connect goes to the IPv6; Host/SNI stay the hostname.
    ipv6 = "2606:2800:220:1:248:1893:25c8:1946"
    seen = _install(monkeypatch, _ok, resolve_to=ipv6)
    rel = _run(_ctx(tmp_path), lambda: media.web.fetch(_candidate("https://v6.example.com/a.png")))
    assert (tmp_path / rel).is_file()
    assert len(seen) == 1
    req = seen[0]
    assert req.url.host == ipv6, "must connect to the validated IPv6 (bracketed in the URL)"
    assert req.headers.get("host", "").startswith("v6.example.com")
    assert req.extensions.get("sni_hostname") == "v6.example.com"


def test_fetch_rejects_when_any_resolved_ip_is_non_global(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # DNS returning a mix (one public, one internal) is rejected — an attacker cannot smuggle an
    # internal address alongside a public one.
    seen = _install(monkeypatch, _ok, resolve_to=[_PUBLIC_IP, "10.0.0.1"])
    with pytest.raises(ValueError):
        _run(_ctx(tmp_path), lambda: media.web.fetch(_candidate("https://mixed.example.com/a.png")))
    assert seen == []


# --- byte cap -----------------------------------------------------------------------------------


def test_fetch_enforces_the_byte_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_mod, "_MAX_DOWNLOAD_BYTES", 64, raising=True)

    def big(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(200, content=b"\x89PNG\r\n\x1a\n" + b"X" * 4096)

    _install(monkeypatch, big)
    with pytest.raises(ValueError):
        _run(
            _ctx(tmp_path),
            lambda: media.web.fetch(_candidate("https://images.example.com/big.png")),
        )


# --- content-encoding: no HTTP decompression bomb before the cap --------------------------------


def test_fetch_requests_identity_encoding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The byte cap must bound WIRE bytes, not decoded bytes: httpx2.iter_bytes() applies
    # Content-Encoding decoders before yielding, so an attacker origin returning gzipped content
    # can expand in memory before the cap runs. fetch must ask for identity so no decoder runs.
    seen = _install(monkeypatch, _ok)
    _run(_ctx(tmp_path), lambda: media.web.fetch(_candidate("https://images.example.com/a.png")))
    assert len(seen) == 1
    assert seen[0].headers.get("accept-encoding") == "identity"


def test_fetch_rejects_a_compressed_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Even if the origin ignores Accept-Encoding: identity and returns a Content-Encoding, fetch
    # must reject it (a decompression bomb: a tiny wire body decodes to gigabytes) rather than let
    # httpx2 decode it. A small decoded payload here would slip past the byte cap on the current
    # code, so this asserts the encoding is rejected outright — RED until that check exists.
    def gz(_request: httpx2.Request, _n: int) -> httpx2.Response:
        body = gzip.compress(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
        return httpx2.Response(
            200, content=body, headers={"content-encoding": "gzip", "content-type": "image/png"}
        )

    seen = _install(monkeypatch, gz)
    with pytest.raises(ValueError):
        _run(
            _ctx(tmp_path),
            lambda: media.web.fetch(_candidate("https://images.example.com/a.png")),
        )
    # the request was sent, then rejected on the response's Content-Encoding; nothing written
    assert len(seen) == 1
    assert list((tmp_path / "artifacts").glob("web-*.bin")) == []


# --- redirects are re-validated -----------------------------------------------------------------


def test_fetch_revalidates_a_redirect_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # follow_redirects is off; a 3xx to an internal host must be re-validated and rejected (the
    # redirect host resolves to a private IP), not blindly followed.
    def redir(_request: httpx2.Request, n: int) -> httpx2.Response:
        return httpx2.Response(302, headers={"location": "https://internal.evil.example.com/x.png"})

    _install(monkeypatch, redir, resolve_to=_PUBLIC_IP)

    # the redirect host resolves internal
    def resolve(host: str):
        return ["10.0.0.9"] if host.startswith("internal.") else [_PUBLIC_IP]

    monkeypatch.setattr(web_mod, "_resolve", resolve)
    with pytest.raises(ValueError):
        _run(_ctx(tmp_path), lambda: media.web.fetch(_candidate("https://ok.example.com/a.png")))
