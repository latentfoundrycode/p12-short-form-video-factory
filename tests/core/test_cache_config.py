"""C-6 contract: the cheap-cache size ceiling (§5.9 / §8.7).

Read from `SFVF_CACHE_MAX_BYTES` (integer bytes); a missing/invalid/negative value falls back to the
default so a bad env var never fails a run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.cache_config import DEFAULT_CACHE_MAX_BYTES, cache_max_bytes


@pytest.fixture(autouse=True)
def _isolate_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # cache_max_bytes() now delegates to app_settings, which reads DATA_ROOT/app_settings.json.
    # Point DATA_ROOT at an empty tmp dir so these env-precedence tests never pick up a real
    # saved defaults file.
    from app import paths

    monkeypatch.setattr(paths, "DATA_ROOT", tmp_path)


def test_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SFVF_CACHE_MAX_BYTES", raising=False)
    assert cache_max_bytes() == DEFAULT_CACHE_MAX_BYTES


def test_reads_integer_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SFVF_CACHE_MAX_BYTES", "1048576")
    assert cache_max_bytes() == 1048576


def test_zero_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    # Zero is a valid ceiling (evict everything cheap); only invalid/negative fall back.
    monkeypatch.setenv("SFVF_CACHE_MAX_BYTES", "0")
    assert cache_max_bytes() == 0


def test_non_integer_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SFVF_CACHE_MAX_BYTES", "not-a-number")
    assert cache_max_bytes() == DEFAULT_CACHE_MAX_BYTES


def test_negative_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SFVF_CACHE_MAX_BYTES", "-5")
    assert cache_max_bytes() == DEFAULT_CACHE_MAX_BYTES
