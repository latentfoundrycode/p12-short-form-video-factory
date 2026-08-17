from __future__ import annotations

import json
from typing import Any, cast


def to_event(line: str) -> dict[str, Any]:
    """Parse one stdout line. JSON objects pass through; anything else becomes a log event."""
    try:
        parsed: object = json.loads(line)
    except json.JSONDecodeError:
        return {"t": "log", "level": "info", "msg": line}
    if isinstance(parsed, dict):
        return cast(dict[str, Any], parsed)
    return {"t": "log", "level": "info", "msg": line}
