"""Frozen contract - Settings F1b: global-defaults store, resolvers, and run-path wiring (R-068).

`app/core/app_settings.py` persists the four PRD 8.7 global defaults - step silence limit, default
concurrency, default step concurrency, and max cache size - under DATA_ROOT. It tolerates a missing
or corrupt file (per-field defaults, never raises on read), validates on write, and exposes
resolvers whose precedence is: explicit env var > stored setting > built-in default. The stored
values are actually CONSUMED: `admit_run` passes the resolved silence limit and step concurrency
into `run_request`, and `cache_config.cache_max_bytes()` reflects the stored ceiling.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import paths
from app.api.runs import admit_run
from app.core import app_settings
from app.core.cache_config import DEFAULT_CACHE_MAX_BYTES
from app.core.supervisor import DEFAULT_SILENCE_SECONDS

_ENV_VARS = (
    "SFVF_SILENCE_LIMIT_SECONDS",
    "SFVF_DEFAULT_CONCURRENCY",
    "SFVF_DEFAULT_STEP_CONCURRENCY",
    "SFVF_CACHE_MAX_BYTES",
)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "DATA_ROOT", tmp_path)
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


# --------------------------------------------------------------------------- store


def test_defaults_when_no_file() -> None:
    s = app_settings.load()
    assert s.silence_limit_seconds == DEFAULT_SILENCE_SECONDS
    assert s.default_concurrency == 1
    assert s.default_step_concurrency == 1
    assert s.cache_max_bytes == DEFAULT_CACHE_MAX_BYTES


def test_update_round_trips() -> None:
    app_settings.update(
        silence_limit_seconds=120.0,
        default_concurrency=3,
        default_step_concurrency=2,
        cache_max_bytes=1234567,
    )
    s = app_settings.load()
    assert s.silence_limit_seconds == 120.0
    assert s.default_concurrency == 3
    assert s.default_step_concurrency == 2
    assert s.cache_max_bytes == 1234567


def test_corrupt_file_falls_back_to_defaults(tmp_path: Path) -> None:
    (tmp_path / "app_settings.json").write_text("{ not valid json", encoding="utf-8")
    s = app_settings.load()  # must not raise
    assert s.silence_limit_seconds == DEFAULT_SILENCE_SECONDS


def test_partial_file_uses_defaults_for_missing_fields(tmp_path: Path) -> None:
    (tmp_path / "app_settings.json").write_text(
        json.dumps({"default_concurrency": 5}), encoding="utf-8"
    )
    s = app_settings.load()
    assert s.default_concurrency == 5
    assert s.silence_limit_seconds == DEFAULT_SILENCE_SECONDS


def test_update_rejects_invalid_values() -> None:
    for bad in (
        {"silence_limit_seconds": 0},
        {"silence_limit_seconds": float("inf")},
        {"default_concurrency": 0},
        {"default_step_concurrency": -1},
        {"cache_max_bytes": -5},
    ):
        with pytest.raises(ValueError):
            app_settings.update(**bad)


# --------------------------------------------------------------------------- resolvers (precedence)


def test_resolver_uses_default_when_unset() -> None:
    assert app_settings.silence_limit_seconds() == DEFAULT_SILENCE_SECONDS
    assert app_settings.default_concurrency() == 1
    assert app_settings.default_step_concurrency() == 1
    assert app_settings.cache_max_bytes() == DEFAULT_CACHE_MAX_BYTES


def test_resolver_uses_stored_when_no_env() -> None:
    app_settings.update(silence_limit_seconds=120.0, default_concurrency=3)
    assert app_settings.silence_limit_seconds() == 120.0
    assert app_settings.default_concurrency() == 3


def test_env_overrides_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    app_settings.update(
        silence_limit_seconds=120.0,
        default_concurrency=3,
        default_step_concurrency=2,
        cache_max_bytes=1000,
    )
    monkeypatch.setenv("SFVF_SILENCE_LIMIT_SECONDS", "45")
    monkeypatch.setenv("SFVF_DEFAULT_CONCURRENCY", "7")
    monkeypatch.setenv("SFVF_DEFAULT_STEP_CONCURRENCY", "4")
    monkeypatch.setenv("SFVF_CACHE_MAX_BYTES", "9999")
    assert app_settings.silence_limit_seconds() == 45.0
    assert app_settings.default_concurrency() == 7
    assert app_settings.default_step_concurrency() == 4
    assert app_settings.cache_max_bytes() == 9999


def test_cache_config_reflects_stored_value() -> None:
    from app.core import cache_config

    app_settings.update(cache_max_bytes=4242)
    assert cache_config.cache_max_bytes() == 4242


# --------------------------------------------------------------------------- run-path wiring (B3)


def test_admit_run_applies_stored_silence_and_step_concurrency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The stored defaults must actually reach the run: admit_run resolves them and passes them into
    # run_request (silence_limit_default, step_concurrency) rather than the hard-coded fallbacks.
    app_settings.update(silence_limit_seconds=123.0, default_step_concurrency=4)
    captured: dict[str, object] = {}

    def fake_run_request(workflow_dir: Path, **kwargs: object) -> None:
        captured.update(kwargs)
        on_started = kwargs.get("on_started")
        if callable(on_started):
            on_started("rid-1")
        return None

    monkeypatch.setattr("app.api.runs.run_request", fake_run_request)
    admit_run(
        tmp_path / "wf",
        params={},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
    )
    assert captured["silence_limit_default"] == 123.0
    assert captured["step_concurrency"] == 4
