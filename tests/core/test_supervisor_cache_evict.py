"""C-6 contract: run_request evicts the cheap cache past the configured ceiling (§5.9).

After a run finishes, the supervisor LRU-evicts the run's cheap cache partition down to
`SFVF_CACHE_MAX_BYTES`. Within the ceiling the cached step survives; a tiny ceiling evicts it. The
`caching` stub performs one ordinary (cheap) `ctx.step`, so its result is exactly what is governed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sfvf.cache import StepCache, step_key

from app.core.env import EnvBlocked, EnvReady
from app.core.supervisor import RunBusy, run_request

STUBS = Path(__file__).resolve().parent.parent / "stubs"
_VERSION = "1.0.0"


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def _run_caching(tmp_path: Path, cache_dir: Path) -> object:
    return run_request(
        STUBS / "caching",
        params={"topic": "t"},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,
        cache_dir=cache_dir,
    )


def test_cheap_cache_kept_within_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SFVF_CACHE_MAX_BYTES", str(100 * 1024 * 1024))
    cache_dir = tmp_path / "cache"
    result = _run_caching(tmp_path, cache_dir)
    assert not isinstance(result, EnvBlocked | RunBusy)
    key = step_key(_VERSION, "compute", {"index": 1})
    assert StepCache(cache_dir / "caching" / "real", partition="cheap").get(key) == {"index": 1}


def test_cheap_cache_evicted_over_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SFVF_CACHE_MAX_BYTES", "1")
    cache_dir = tmp_path / "cache"
    result = _run_caching(tmp_path, cache_dir)
    assert not isinstance(result, EnvBlocked | RunBusy)
    key = step_key(_VERSION, "compute", {"index": 1})
    assert StepCache(cache_dir / "caching" / "real", partition="cheap").get(key) is None
