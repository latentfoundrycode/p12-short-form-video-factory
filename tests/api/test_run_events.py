import json
import shutil
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.core.supervisor as supervisor_mod
from app.core.env import EnvReady
from app.main import create_app

STUBS = Path(__file__).resolve().parent.parent / "stubs"
TERMINAL = {"complete", "partial", "stopped", "stopped-budget", "failed"}


@pytest.fixture(autouse=True)
def _clear_supervisor_state() -> None:
    with supervisor_mod._lock:
        supervisor_mod._active.clear()
        supervisor_mod._runs.clear()
    yield
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with supervisor_mod._lock:
            if not supervisor_mod._active and not supervisor_mod._runs:
                break
        time.sleep(0.05)
    with supervisor_mod._lock:
        supervisor_mod._active.clear()
        supervisor_mod._runs.clear()


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def _install_stub(workflows_dir: Path, name: str) -> None:
    dest = workflows_dir / name
    shutil.copytree(STUBS / name, dest)
    (dest / "requirements.txt").write_text("", encoding="utf-8")


def _client(tmp_path: Path, *, ensure_env: object = _ready) -> TestClient:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    runs_dir = tmp_path / "runs"
    return TestClient(
        create_app(
            workflows_dir=workflows_dir,
            runs_dir=runs_dir,
            ensure_env=ensure_env,  # type: ignore[arg-type]
        )
    )


def _wait_terminal(client: TestClient, workflow_id: str, run_id: str, timeout: float = 15) -> dict:
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/workflows/{workflow_id}/runs/{run_id}")
        if response.status_code == 404:
            time.sleep(0.05)
            continue
        assert response.status_code == 200
        last = response.json()
        if last["status"] in TERMINAL:
            return last
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not reach a terminal status; last={last}")


def _collect_sse_envelopes(client: TestClient, url: str) -> tuple[int, list[dict]]:
    envelopes: list[dict] = []
    with client.stream("GET", url) as response:
        status = response.status_code
        if status != 200:
            return status, envelopes
        for line in response.iter_lines():
            if not line:
                continue
            if line.startswith("data:"):
                payload = line[5:].lstrip()
                envelopes.append(json.loads(payload))
    return 200, envelopes


def test_sse_replays_finished_run_then_closes(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    client = _client(tmp_path)

    launched = client.post(
        "/api/workflows/succeeds/runs",
        json={"params": {"topic": "test"}, "video_count": 1, "concurrency": 1},
    )
    assert launched.status_code == 202
    run_id = launched.json()["run_id"]
    _wait_terminal(client, "succeeds", run_id)

    status, envelopes = _collect_sse_envelopes(
        client, f"/api/workflows/succeeds/runs/{run_id}/events"
    )
    assert status == 200
    bodies = [item["event"] for item in envelopes]
    assert {"t": "log", "level": "info", "msg": "ok"} in bodies
    assert {"t": "result", "video": "final.mp4", "caption": "hello"} in bodies
    ok_idx = bodies.index({"t": "log", "level": "info", "msg": "ok"})
    result_idx = bodies.index({"t": "result", "video": "final.mp4", "caption": "hello"})
    assert ok_idx < result_idx
    for item in envelopes:
        assert {"ts", "source", "event"} <= set(item)


def test_sse_catch_up_then_live_to_terminal(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    client = _client(tmp_path)

    launched = client.post(
        "/api/workflows/succeeds/runs",
        json={"params": {"topic": "test"}, "video_count": 1, "concurrency": 1},
    )
    assert launched.status_code == 202
    run_id = launched.json()["run_id"]

    status, envelopes = _collect_sse_envelopes(
        client, f"/api/workflows/succeeds/runs/{run_id}/events"
    )
    assert status == 200
    assert envelopes
    bodies = [item["event"] for item in envelopes]
    assert {"t": "log", "level": "info", "msg": "ok"} in bodies
    assert {"t": "result", "video": "final.mp4", "caption": "hello"} in bodies
    detail = client.get(f"/api/workflows/succeeds/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] in TERMINAL


def test_sse_unknown_run_is_404(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    client = _client(tmp_path)

    started = time.monotonic()
    response = client.get("/api/workflows/succeeds/runs/no-such-run/events")
    elapsed = time.monotonic() - started
    assert response.status_code == 404
    assert elapsed >= 1.5


def test_sse_tolerates_torn_last_line(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    client = _client(tmp_path)

    launched = client.post(
        "/api/workflows/succeeds/runs",
        json={"params": {"topic": "test"}, "video_count": 1, "concurrency": 1},
    )
    run_id = launched.json()["run_id"]
    _wait_terminal(client, "succeeds", run_id)

    events_path = tmp_path / "runs" / "succeeds" / run_id / "events.jsonl"
    with events_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"ts":"t","source":"01","event":{"t":"log"')

    status, envelopes = _collect_sse_envelopes(
        client, f"/api/workflows/succeeds/runs/{run_id}/events"
    )
    assert status == 200
    bodies = [item["event"] for item in envelopes]
    assert {"t": "log", "level": "info", "msg": "ok"} in bodies
    assert {"t": "result", "video": "final.mp4", "caption": "hello"} in bodies
