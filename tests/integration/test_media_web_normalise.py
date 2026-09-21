"""Frozen contract — web-image-sourcing increment 3b: byte validation + normalise.

After the SSRF-guarded download (increment 3a), the fetched bytes are STILL untrusted. Per
docs/DESIGN §7.2 the byte pipeline must, before anything is written to the run workspace or the
library:

- **type-gate by MAGIC BYTES** (not suffix): allow only png / jpeg / webp / (static) gif; SVG is
  EXCLUDED (XML -> XXE/SSRF-on-render); everything else is rejected;
- **bound the decode** (decompression / pixel bomb): reject when the declared pixel count exceeds a
  cap BEFORE the full bitmap is allocated (a ~20 KB file can declare gigapixels);
- **reject animated** images (GIF/WebP/APNG frame bombs);
- **decode -> re-encode -> strip** all metadata (EXIF/ICC/text) and trailing data, and DISCARD the
  originals — this is what defeats polyglot / EXIF-tracker / embedded payloads, not the magic check;
- name the canonical file by a WIDE content hash (sha256[:16], 64-bit) of the RE-ENCODED bytes.

The seam under test is `media.web._normalise_image(data: bytes) -> tuple[bytes, str]` returning
(canonical_bytes, extension) or raising ValueError. `fetch` runs it after the download and writes
the canonical image (never the original bytes).
"""

import hashlib
import io
import struct
import zlib

import pytest
from PIL import Image
from sfvf.media import web as web_mod

# --- fixtures -----------------------------------------------------------------------------------


def _png(w: int = 8, h: int = 8, color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_with_exif() -> bytes:
    img = Image.new("RGB", (16, 16), (10, 120, 200))
    exif = img.getexif()
    exif[0x010F] = "SECRET-CAMERA-MAKE"  # Make tag -> must not survive normalise
    exif[0x0110] = "TRACKER-MODEL"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif, quality=92)
    return buf.getvalue()


def _animated_gif() -> bytes:
    frames = [Image.new("P", (8, 8), i) for i in range(3)]
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=50, loop=0)
    return buf.getvalue()


def _pixel_bomb_png(w: int = 40000, h: int = 40000) -> bytes:
    # a tiny file that DECLARES a gigapixel image: valid signature + IHDR(w, h) + minimal IDAT +
    # IEND. Image.open reads the IHDR size WITHOUT decoding IDAT, so the pixel-bound check must
    # reject on `.size` before any bitmap is allocated. (40000*40000 = 1.6 Gpixel.)
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")  # nonsense, never decoded
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


# --- type gate: magic bytes, SVG excluded, wrong-magic rejected ---------------------------------


def test_normalise_accepts_a_valid_png_and_reencodes_it() -> None:
    canonical, ext = web_mod._normalise_image(_png())
    assert ext == "png"
    out = Image.open(io.BytesIO(canonical))
    assert out.format == "PNG" and out.size == (8, 8)


@pytest.mark.parametrize(
    "data",
    [
        b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>",
        b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        b"GIF-not-really",
        b"\x00\x01\x02\x03 not an image",
        b"%PDF-1.7\n...",
        b"<!DOCTYPE html><html></html>",
        b"",
    ],
)
def test_normalise_rejects_non_image_and_svg_bytes(data: bytes) -> None:
    with pytest.raises(ValueError):
        web_mod._normalise_image(data)


def test_normalise_rejects_a_png_suffix_lie_by_magic() -> None:
    # bytes whose content is not a real image must be rejected regardless of any claimed type
    with pytest.raises(ValueError):
        web_mod._normalise_image(b"\x89PNG\r\n\x1a\nnot actually a png body")


# --- decompression / pixel bomb -----------------------------------------------------------------


def test_normalise_rejects_a_pixel_bomb_before_decode() -> None:
    with pytest.raises(ValueError):
        web_mod._normalise_image(_pixel_bomb_png())


def test_pixel_bound_is_a_sane_ceiling() -> None:
    # the cap exists, is a finite int, and is well below Pillow's ~89 Mpixel default bomb threshold
    assert isinstance(web_mod._MAX_IMAGE_PIXELS, int)
    assert 1_000_000 <= web_mod._MAX_IMAGE_PIXELS <= 89_000_000


# --- animation bound ----------------------------------------------------------------------------


def test_normalise_rejects_an_animated_image() -> None:
    with pytest.raises(ValueError):
        web_mod._normalise_image(_animated_gif())


# --- re-encode strips EXIF / metadata / trailing (polyglot) -------------------------------------


def test_normalise_strips_exif_from_jpeg() -> None:
    canonical, ext = web_mod._normalise_image(_jpeg_with_exif())
    assert ext in ("jpg", "jpeg")
    out = Image.open(io.BytesIO(canonical))
    assert not dict(out.getexif()), "EXIF must be stripped by re-encode"
    assert b"SECRET-CAMERA-MAKE" not in canonical and b"TRACKER-MODEL" not in canonical


def test_normalise_discards_trailing_polyglot_payload() -> None:
    # a valid PNG with an appended ZIP/HTML trailer (polyglot). The re-encode must decode the pixels
    # and drop everything else, so the trailer cannot survive into the canonical bytes.
    polyglot = _png() + b"PK\x03\x04" + b"<script>evil()</script>" + b"TRAILER-MARKER"
    canonical, _ext = web_mod._normalise_image(polyglot)
    assert b"PK\x03\x04" not in canonical
    assert b"TRAILER-MARKER" not in canonical
    assert b"<script>" not in canonical
    Image.open(io.BytesIO(canonical)).verify()  # still a valid image


# --- content-addressed naming (wide hash) + collision -------------------------------------------


def test_normalise_output_is_deterministic() -> None:
    a, _ = web_mod._normalise_image(_png(color=(1, 2, 3)))
    b, _ = web_mod._normalise_image(_png(color=(1, 2, 3)))
    assert a == b, "same input -> identical canonical bytes (content-addressable)"


def test_distinct_images_get_distinct_wide_content_hashes() -> None:
    a, _ = web_mod._normalise_image(_png(color=(1, 2, 3)))
    b, _ = web_mod._normalise_image(_png(color=(250, 250, 250)))
    ha, hb = web_mod._content_hash(a), web_mod._content_hash(b)
    assert ha != hb
    assert len(ha) >= 16, "content hash must be >= 64-bit (sha256[:16]), not the 32-bit stub width"
    assert ha == hashlib.sha256(a).hexdigest()[:16]
