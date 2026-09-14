from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.paths import is_safe_path_segment


def read_last_learned(state_dir: Path, workflow_id: str) -> str | None:
    if not is_safe_path_segment(workflow_id):
        return None
    path = state_dir / f"{workflow_id}.json"
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("last_learned")
    return value if isinstance(value, str) else None


def write_last_learned(state_dir: Path, workflow_id: str, iso: str) -> None:
    if not is_safe_path_segment(workflow_id):
        return
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / f"{workflow_id}.json").write_text(
        json.dumps({"last_learned": iso}), encoding="utf-8"
    )
