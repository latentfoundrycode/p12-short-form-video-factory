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

import struct
import zlib
from pathlib import Path

import httpx2
import pytest
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
    assert target.is_file() and target.read_bytes() == _png_bytes()
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
        _run(_ctx(tmp_path), lambda: media.web.fetch(_candidate("https://nope.example.invalid/a.png")))
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
        "::ffff:127.0.0.1",
    ],
)
def test_fetch_rejects_a_non_global_resolved_ip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ip: str
) -> None:
    seen = _install(monkeypatch, _ok, resolve_to=ip)
    with pytest.raises(ValueError):
        _run(_ctx(tmp_path), lambda: media.web.fetch(_candidate("https://evil.example.com/a.png")))
    assert seen == [], "a non-global resolved IP must be rejected before any request"


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
