import json
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.core.supervisor as supervisor_mod
from app.core.env import EnvBlocked, EnvReady
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
        # Admission returns before request.json is written; tolerate 404 briefly.
        if response.status_code == 404:
            time.sleep(0.05)
            continue
        assert response.status_code == 200
        last = response.json()
        if last["status"] in TERMINAL:
            return last
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not reach a terminal status; last={last}")


def _wait_run_dir(parent: Path, timeout: float = 5) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if parent.is_dir():
            found = [path for path in parent.iterdir() if path.is_dir()]
            if found:
                return found[0]
        time.sleep(0.02)
    raise AssertionError(f"no run dir under {parent}")


def _wait_source_event(run_dir: Path, source: str, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        path = run_dir / "events.jsonl"
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                envelope = json.loads(line)
                if envelope.get("source") == source:
                    return
        time.sleep(0.02)
    raise AssertionError(f"no event from {source} in {run_dir}")


def test_launch_and_read_completes(tmp_path: Path) -> None:
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
    assert isinstance(run_id, str) and run_id

    detail = _wait_terminal(client, "succeeds", run_id)
    assert detail["status"] == "complete"
    assert detail["run_id"] == run_id
    assert any(video.get("status") == "complete" for video in detail["video_records"])
    assert detail["videos"][0]["status"] == "complete"


def test_list_returns_runs_newest_first(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    client = _client(tmp_path)

    first = client.post(
        "/api/workflows/succeeds/runs",
        json={"params": {"topic": "a"}, "video_count": 1, "concurrency": 1},
    )
    assert first.status_code == 202
    first_id = first.json()["run_id"]
    _wait_terminal(client, "succeeds", first_id)

    second = client.post(
        "/api/workflows/succeeds/runs",
        json={"params": {"topic": "b"}, "video_count": 1, "concurrency": 1},
    )
    assert second.status_code == 202
    second_id = second.json()["run_id"]
    _wait_terminal(client, "succeeds", second_id)

    listed = client.get("/api/workflows/succeeds/runs")
    assert listed.status_code == 200
    body = listed.json()
    runs = body["runs"]
    assert [item["run_id"] for item in runs] == [second_id, first_id]
    for item in runs:
        assert {"run_id", "status", "started_utc", "ended_utc", "videos"} <= set(item)
        assert item["status"] == "complete"


def test_list_missing_runs_dir_is_empty(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    client = _client(tmp_path)
    listed = client.get("/api/workflows/succeeds/runs")
    assert listed.status_code == 200
    assert listed.json() == {"runs": []}


def test_graceful_stop_ends_stopped(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "cooperates")
    client = _client(tmp_path)

    launched = client.post(
        "/api/workflows/cooperates/runs",
        json={"params": {"topic": "test"}, "video_count": 1, "concurrency": 1},
    )
    assert launched.status_code == 202
    run_id = launched.json()["run_id"]

    run_dir = _wait_run_dir(tmp_path / "runs" / "cooperates")
    _wait_source_event(run_dir, "01")

    stopped = client.post(
        f"/api/workflows/cooperates/runs/{run_id}/stop",
        json={"mode": "graceful"},
    )
    assert stopped.status_code == 200
    assert stopped.json() == {"run_id": run_id, "mode": "graceful"}

    detail = _wait_terminal(client, "cooperates", run_id)
    assert detail["status"] == "stopped"


def test_busy_second_launch_is_409(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")

    started = threading.Event()
    release = threading.Event()

    def hold_env(*_args: object, **_kwargs: object) -> EnvReady:
        started.set()
        assert release.wait(timeout=5)
        return EnvReady(python=Path(sys.executable))

    client = _client(tmp_path, ensure_env=hold_env)
    first_box: list[object] = []

    def first() -> None:
        first_box.append(
            client.post(
                "/api/workflows/succeeds/runs",
                json={"params": {"topic": "test"}, "video_count": 1, "concurrency": 1},
            )
        )

    thread = threading.Thread(target=first)
    thread.start()
    assert started.wait(timeout=5)

    refused = client.post(
        "/api/workflows/succeeds/runs",
        json={"params": {"topic": "test"}, "video_count": 1, "concurrency": 1},
    )
    assert refused.status_code == 409

    release.set()
    thread.join(timeout=15)
    assert not thread.is_alive()
    assert first_box
    first_response = first_box[0]
    assert first_response.status_code == 202  # type: ignore[union-attr]

    # Drain the background run so it does not leak into later tests.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with supervisor_mod._lock:
            if "succeeds" not in supervisor_mod._active:
                return
        time.sleep(0.05)
    raise AssertionError("first run did not release the active slot")


def test_env_blocked_is_422_and_creates_no_run_folder(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    reason = "Python 3.12 is required but not installed"
    client = _client(
        tmp_path,
        ensure_env=lambda *_a, **_k: EnvBlocked(reason=reason),
    )

    response = client.post(
        "/api/workflows/succeeds/runs",
        json={"params": {"topic": "test"}, "video_count": 1, "concurrency": 1},
    )
    assert response.status_code == 422
    assert response.json() == {"reason": reason}
    runs_dir = tmp_path / "runs"
    assert not runs_dir.exists() or not any(runs_dir.rglob("*"))


def test_unknown_workflow_is_404(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    client = _client(tmp_path)
    response = client.post(
        "/api/workflows/no-such/runs",
        json={"params": {}, "video_count": 1, "concurrency": 1},
    )
    assert response.status_code == 404


def test_invalid_workflow_is_422(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    broken = workflows_dir / "broken"
    broken.mkdir()
    (broken / "workflow.toml").write_text("[[[not toml\n", encoding="utf-8")
    client = _client(tmp_path)
    response = client.post(
        "/api/workflows/broken/runs",
        json={"params": {}, "video_count": 1, "concurrency": 1},
    )
    assert response.status_code == 422


def test_get_unknown_run_is_404(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    client = _client(tmp_path)
    response = client.get("/api/workflows/succeeds/runs/no-such-run")
    assert response.status_code == 404


def test_stop_finished_run_is_404(tmp_path: Path) -> None:
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
    stopped = client.post(
        f"/api/workflows/succeeds/runs/{run_id}/stop",
        json={"mode": "hard"},
    )
    assert stopped.status_code == 404
