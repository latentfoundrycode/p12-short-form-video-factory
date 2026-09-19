"""Turn a workflow-supplied reference/frame (a video-relative file OR an http(s) URL) into a URL a
provider can fetch. Local files inline as a data URI (option 1); http(s) passes through. This is
chassis-level and shared by every video adapter, never handled per workflow."""

from __future__ import annotations

import base64
import mimetypes
from typing import Any


def image_ref_url(ctx: Any, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    data = (ctx.paths.video / path).read_bytes()
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"
