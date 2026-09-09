"""C-2 contract: `ctx.forecast(...)` emits a forecast event (soft reservation, §5.4a).

A workflow whose price follows from how the run turns out (e.g. how many shots the script yields)
declares, mid-run, what the remainder will cost. The SDK surfaces this as a `forecast` event:

    {"t":"forecast","meter":"higgsfield","unit":"credits","amount":720,"note":"60 shots"}

It is a soft reservation — visible on the card and in Statistics, not itself blocking (the atomic
pre-flight check that consumes it is C-3). `note` is optional and omitted when absent. No network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sfvf.context import Context, ContextFile, ContextPaths


def _ctx(tmp: Path) -> Context:
    return Context(
        ContextFile(
            settings={},
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
        )
    )


def _forecasts(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    events: list[dict] = []
    for line in capsys.readouterr().out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("t") == "forecast":
                events.append(e)
    return events


def test_forecast_emits_event_with_note(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _ctx(tmp_path).forecast("higgsfield", "credits", 720, note="60 shots")
    fc = _forecasts(capsys)
    assert len(fc) == 1
    assert fc[0] == {
        "t": "forecast",
        "meter": "higgsfield",
        "unit": "credits",
        "amount": 720,
        "note": "60 shots",
    }


def test_forecast_without_note_omits_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _ctx(tmp_path).forecast("openrouter", "usd", 1.5)
    fc = _forecasts(capsys)
    assert len(fc) == 1
    assert fc[0] == {"t": "forecast", "meter": "openrouter", "unit": "usd", "amount": 1.5}
    assert "note" not in fc[0]
