"""F-5 contract (part C): the scheduler timer wires into the app lifespan, opt-in, off by default.

The architecture puts the scheduler on "a timer inside the backend". This increment arms that
timer from the FastAPI app lifespan when `create_app(enable_scheduler=True)`, stopping it on
shutdown. It
is OFF by default (a conservative operational default: an always-on driver spawns run subprocesses,
and — for entries that opt into real spend — could launch unattended paid work; arming is therefore
an explicit choice, still gated per-entry by `allow_real_spend` and the budget). The production
entrypoint enables it from an environment variable.

Uses an empty schedules file so the armed driver fires nothing during the test.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.schedules import write_schedules
from app.main import create_app


def _app(tmp_path: Path, *, enable_scheduler: bool):
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    schedules_path = tmp_path / "schedules.json"
    write_schedules(schedules_path, [])
    return create_app(
        workflows_dir=workflows_dir,
        runs_dir=tmp_path / "runs",
        schedules_path=schedules_path,
        enable_scheduler=enable_scheduler,
    )


def test_scheduler_off_by_default(tmp_path: Path) -> None:
    app = create_app(
        workflows_dir=tmp_path / "workflows",
        runs_dir=tmp_path / "runs",
        schedules_path=tmp_path / "schedules.json",
    )
    (tmp_path / "workflows").mkdir(exist_ok=True)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert getattr(app.state, "scheduler_driver", None) is None


def test_scheduler_armed_when_enabled_and_stopped_on_shutdown(tmp_path: Path) -> None:
    app = _app(tmp_path, enable_scheduler=True)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        driver = app.state.scheduler_driver
        assert driver is not None
        assert driver.running is True
    # Leaving the TestClient context runs shutdown, which must stop the driver.
    assert app.state.scheduler_driver.running is False
