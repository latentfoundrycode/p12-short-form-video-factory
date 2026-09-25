"""Per-asset access grants for the owner library pool.

Grants live in `grants.json` beside the owner-pool root (shape like the library's `aliases.json`):
an asset id maps to either `{"all": true}` or `{"workflows": [ids]}`. Ungranted assets deny.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .cache import _write_json_atomic

_RETRY_ATTEMPTS = 5
_RETRY_SLEEP_S = 0.01


class GrantError(ValueError):
    """A grant payload does not match the allowed shape."""


def _validate_grant(grant: object) -> dict[str, Any]:
    if not isinstance(grant, dict):
        raise GrantError("grant must be a dict")
    keys = set(grant.keys())
    if keys == {"all"}:
        if not isinstance(grant["all"], bool):
            raise GrantError("all must be a bool")
        return {"all": grant["all"]}
    if keys == {"workflows"}:
        workflows = grant["workflows"]
        if not isinstance(workflows, list):
            raise GrantError("workflows must be a list")
        if not all(isinstance(item, str) for item in workflows):
            raise GrantError("workflow ids must be strings")
        return {"workflows": list(workflows)}
    raise GrantError("grant must be exactly one of {'all': bool} or {'workflows': [str, ...]}")


def _load_grants_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GrantError("grants file is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise GrantError("grants file is not a JSON object")
    return raw


def _write_grants_atomic(path: Path, payload: object) -> None:
    last_exc: OSError | None = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            _write_json_atomic(path, payload)
            return
        except OSError as exc:
            last_exc = exc
            if attempt + 1 >= _RETRY_ATTEMPTS:
                raise
            time.sleep(_RETRY_SLEEP_S)
    if last_exc is not None:
        raise last_exc


class GrantStore:
    """Mutable per-asset workflow access grants rooted at an owner-pool directory."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._grants_path = root / "grants.json"

    def set_grant(self, asset_id: str, grant: dict[str, Any]) -> None:
        validated = _validate_grant(grant)
        grants = _load_grants_file(self._grants_path)
        grants[asset_id] = validated
        _write_grants_atomic(self._grants_path, grants)

    def get_grant(self, asset_id: str) -> dict[str, Any]:
        try:
            grants = _load_grants_file(self._grants_path)
        except GrantError:
            return {"workflows": []}
        entry = grants.get(asset_id)
        if entry is None:
            return {"workflows": []}
        try:
            return _validate_grant(entry)
        except GrantError:
            return {"workflows": []}

    def grant_allows(self, asset_id: str, workflow_id: str) -> bool:
        grant = self.get_grant(asset_id)
        if grant.get("all") is True:
            return True
        workflows = grant.get("workflows", [])
        if isinstance(workflows, list):
            return workflow_id in workflows
        return False
