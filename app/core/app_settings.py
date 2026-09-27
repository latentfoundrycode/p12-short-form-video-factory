"""Persisted global defaults (PRD §8.7) under DATA_ROOT with env override resolvers."""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.core.cache_config import DEFAULT_CACHE_MAX_BYTES
from app.core.records import write_json_atomic
from app.core.supervisor import DEFAULT_SILENCE_SECONDS

_ENV_SILENCE = "SFVF_SILENCE_LIMIT_SECONDS"
_ENV_DEFAULT_CONCURRENCY = "SFVF_DEFAULT_CONCURRENCY"
_ENV_DEFAULT_STEP_CONCURRENCY = "SFVF_DEFAULT_STEP_CONCURRENCY"
_ENV_CACHE_MAX_BYTES = "SFVF_CACHE_MAX_BYTES"

_FIELD_NAMES = (
    "silence_limit_seconds",
    "default_concurrency",
    "default_step_concurrency",
    "cache_max_bytes",
)


@dataclass
class AppSettings:
    silence_limit_seconds: float
    default_concurrency: int
    default_step_concurrency: int
    cache_max_bytes: int


def _store_path() -> Path:
    import app.paths as paths

    return paths.DATA_ROOT / "app_settings.json"


def _read_store_dict() -> dict[str, Any] | None:
    path = _store_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _parse_silence_value(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def _parse_int_setting(raw: object) -> int | None:
    if type(raw) is not int or isinstance(raw, bool):
        return None
    if raw < 1:
        return None
    return raw


def _builtin() -> AppSettings:
    return AppSettings(
        silence_limit_seconds=DEFAULT_SILENCE_SECONDS,
        default_concurrency=1,
        default_step_concurrency=1,
        cache_max_bytes=DEFAULT_CACHE_MAX_BYTES,
    )


def load() -> AppSettings:
    """Read persisted settings; missing or invalid data falls back per field. Never raises."""
    built = _builtin()
    data = _read_store_dict()
    if data is None:
        return built
    silence = _parse_silence_value(data.get("silence_limit_seconds"))
    concurrency = _parse_int_setting(data.get("default_concurrency"))
    step_concurrency = _parse_int_setting(data.get("default_step_concurrency"))
    cache = _parse_int_setting(data.get("cache_max_bytes"))
    return AppSettings(
        silence_limit_seconds=silence if silence is not None else built.silence_limit_seconds,
        default_concurrency=concurrency if concurrency is not None else built.default_concurrency,
        default_step_concurrency=(
            step_concurrency if step_concurrency is not None else built.default_step_concurrency
        ),
        cache_max_bytes=cache if cache is not None else built.cache_max_bytes,
    )


def _validate(settings: AppSettings) -> None:
    if not math.isfinite(settings.silence_limit_seconds) or settings.silence_limit_seconds <= 0:
        raise ValueError("silence_limit_seconds must be finite and > 0")
    for name in ("default_concurrency", "default_step_concurrency", "cache_max_bytes"):
        value = getattr(settings, name)
        if type(value) is not int or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} must be an int >= 1")


_INT_UPDATE_FIELDS = frozenset(
    {"default_concurrency", "default_step_concurrency", "cache_max_bytes"}
)


def _validate_update_fields(fields: dict[str, object]) -> None:
    for name, value in fields.items():
        if isinstance(value, bool):
            raise ValueError(f"{name} must not be a bool")
        if name in _INT_UPDATE_FIELDS:
            if type(value) is not int:
                raise ValueError(f"{name} must be an int >= 1")
        elif name == "silence_limit_seconds" and not isinstance(value, int | float):
            raise ValueError("silence_limit_seconds must be finite and > 0")


def update(**fields: float | int) -> AppSettings:
    _validate_update_fields(dict(fields))
    current = load()
    merged = AppSettings(
        silence_limit_seconds=float(
            fields.get("silence_limit_seconds", current.silence_limit_seconds)
        ),
        default_concurrency=int(fields.get("default_concurrency", current.default_concurrency)),
        default_step_concurrency=int(
            fields.get("default_step_concurrency", current.default_step_concurrency)
        ),
        cache_max_bytes=int(fields.get("cache_max_bytes", current.cache_max_bytes)),
    )
    _validate(merged)
    write_json_atomic(_store_path(), asdict(merged))
    return merged


def _env_silence() -> float | None:
    raw = os.environ.get(_ENV_SILENCE)
    if raw is None:
        return None
    return _parse_silence_value(raw)


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        parsed = int(raw)
    except ValueError:
        return None
    return _parse_int_setting(parsed)


def _env_cache_max_bytes() -> int | None:
    raw = os.environ.get(_ENV_CACHE_MAX_BYTES)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def _stored_silence(data: dict[str, Any] | None) -> float | None:
    if data is None or "silence_limit_seconds" not in data:
        return None
    return _parse_silence_value(data["silence_limit_seconds"])


def _stored_int(data: dict[str, Any] | None, key: str) -> int | None:
    if data is None or key not in data:
        return None
    return _parse_int_setting(data[key])


def _resolve_silence_limit_seconds() -> tuple[float, str]:
    env = _env_silence()
    if env is not None:
        return env, "env"
    data = _read_store_dict()
    stored = _stored_silence(data)
    if stored is not None:
        return stored, "stored"
    return DEFAULT_SILENCE_SECONDS, "default"


def _resolve_default_concurrency() -> tuple[int, str]:
    env = _env_int(_ENV_DEFAULT_CONCURRENCY)
    if env is not None:
        return env, "env"
    data = _read_store_dict()
    stored = _stored_int(data, "default_concurrency")
    if stored is not None:
        return stored, "stored"
    return 1, "default"


def _resolve_default_step_concurrency() -> tuple[int, str]:
    env = _env_int(_ENV_DEFAULT_STEP_CONCURRENCY)
    if env is not None:
        return env, "env"
    data = _read_store_dict()
    stored = _stored_int(data, "default_step_concurrency")
    if stored is not None:
        return stored, "stored"
    return 1, "default"


def _resolve_cache_max_bytes() -> tuple[int, str]:
    env = _env_cache_max_bytes()
    if env is not None:
        return env, "env"
    data = _read_store_dict()
    stored = _stored_int(data, "cache_max_bytes")
    if stored is not None:
        return stored, "stored"
    return DEFAULT_CACHE_MAX_BYTES, "default"


def silence_limit_seconds() -> float:
    return _resolve_silence_limit_seconds()[0]


def default_concurrency() -> int:
    return _resolve_default_concurrency()[0]


def default_step_concurrency() -> int:
    return _resolve_default_step_concurrency()[0]


def cache_max_bytes() -> int:
    return _resolve_cache_max_bytes()[0]


def effective_defaults() -> dict[str, dict[str, float | int | str]]:
    resolvers = {
        "silence_limit_seconds": _resolve_silence_limit_seconds,
        "default_concurrency": _resolve_default_concurrency,
        "default_step_concurrency": _resolve_default_step_concurrency,
        "cache_max_bytes": _resolve_cache_max_bytes,
    }
    out: dict[str, dict[str, float | int | str]] = {}
    for name in _FIELD_NAMES:
        effective, source = resolvers[name]()
        out[name] = {"effective": effective, "source": source}
    return out
