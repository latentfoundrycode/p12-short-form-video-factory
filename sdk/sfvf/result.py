from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Result:
    video: Path
    caption: str | None = None
    hashtags: list[str] | None = None
    cover_frame_s: float = 1.0
    notes: str | None = None
    extra: dict[str, Any] | None = None
