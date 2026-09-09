"""C-2 contract: the supervisor records forecast events into request.json as soft reservations.

A `forecast` event updates `request.json`'s `forecast` block to `{meter: {unit, amount, at_utc}}`
(Architecture §4.1). The latest forecast for a meter supersedes earlier ones; distinct meters
accumulate; `at_utc` stamps when the engine recorded it. A run with no forecast events records no
`forecast` block. It is a soft (non-blocking) reservation here — the atomic pre-flight that acts on
it is C-3. No network, no spend.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.core.env import EnvBlocked, EnvReady
from app.core.records import read_request
from app.core.supervisor import RunBusy, run_request

STUBS = Path(__file__).resolve().parent.parent / "stubs"


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def _run(workflow: Path, tmp_path: Path) -> Path:
    result = run_request(
        workflow,
        params={},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,
    )
    assert not isinstance(result, EnvBlocked | RunBusy)
    return next(next((tmp_path / "runs").iterdir()).iterdir())


def test_request_records_latest_forecast_per_meter(tmp_path: Path) -> None:
    request = read_request(_run(STUBS / "emits_forecast", tmp_path))
    assert request.forecast is not None
    hf = request.forecast["higgsfield"]
    assert hf["unit"] == "credits"
    assert hf["amount"] == pytest.approx(720)  # the later forecast supersedes 500
    assert isinstance(hf["at_utc"], str) and hf["at_utc"]
    orr = request.forecast["openrouter"]
    assert orr["unit"] == "usd"
    assert orr["amount"] == pytest.approx(1.2)


def test_no_forecast_events_records_no_forecast_block(tmp_path: Path) -> None:
    request = read_request(_run(STUBS / "succeeds", tmp_path))
    assert request.status == "complete"
    assert request.forecast is None


def test_forecast_block_redacts_injected_secret(tmp_path: Path) -> None:
    # request.json's forecast block is a write path: an injected secret surfacing in a forecast
    # (here, in the meter) must be redacted, like every other write path (§8).
    result = run_request(
        STUBS / "leaks_forecast_secret",
        params={},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,
        secrets={"OPENROUTER_API_KEY": "sk-secret-xyz"},
    )
    assert not isinstance(result, EnvBlocked | RunBusy)
    request = read_request(next(next((tmp_path / "runs").iterdir()).iterdir()))
    dumped = json.dumps(request.forecast)
    assert "sk-secret-xyz" not in dumped
    assert "[REDACTED]" in dumped
