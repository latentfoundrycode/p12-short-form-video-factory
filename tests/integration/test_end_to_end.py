"""Task 6 — full-stack integration proof.

Drives a real run through the whole chassis in one flow: HTTP run API →
supervisor → prepare-once → fan-out video subprocesses → events.jsonl → SSE
replay → records → final aggregate status. Everything is real except the
per-workflow venv build, which is substituted with the current interpreter
(the real environment manager is proven separately; see the Task 6 PR / status).
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.core.supervisor as supervisor_mod
from app.core.env import EnvReady
from app.main import create_app

STUBS = Path(__file__).resolve().parent.parent / "stubs"
TERMINAL = {"complete", "partial", "stopped", "stopped-budget", "failed"}


@pytest.fixture(autouse=True)
def _clear_supervisor_state() -> Iterator[None]:
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


def _client(tmp_path: Path) -> TestClient:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "prepares")
    return TestClient(
        create_app(
            workflows_dir=workflows_dir,
            runs_dir=tmp_path / "runs",
            ensure_env=_ready,  # type: ignore[arg-type]
        )
    )


def _wait_terminal(client: TestClient, run_id: str, timeout: float = 20) -> dict:
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/workflows/prepares/runs/{run_id}")
        if response.status_code == 404:
            time.sleep(0.05)
            continue
        last = response.json()
        if last["status"] in TERMINAL:
            return last
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} never reached a terminal status; last={last}")


def _collect_sse(client: TestClient, run_id: str) -> list[dict]:
    envelopes: list[dict] = []
    with client.stream("GET", f"/api/workflows/prepares/runs/{run_id}/events") as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data:"):
                envelopes.append(json.loads(line[5:].lstrip()))
    return envelopes


def test_prepare_fanout_events_records_final_status(tmp_path: Path) -> None:
    client = _client(tmp_path)

    # request → 202 with a run id
    launched = client.post(
        "/api/workflows/prepares/runs",
        json={"params": {"topic": "e2e"}, "video_count": 2, "concurrency": 2},
    )
    assert launched.status_code == 202
    run_id = launched.json()["run_id"]

    # → prepare-once → fan-out → records → final status
    detail = _wait_terminal(client, run_id)
    assert detail["status"] == "complete"
    assert [v["status"] for v in detail["videos"]] == ["complete", "complete"]
    assert len(detail["video_records"]) == 2
    # the shared prepare result propagated into every video
    for record in detail["video_records"]:
        assert record["status"] == "complete"
        assert record["result"]["caption"] == "hello from prep"

    # events.jsonl captured the whole run and replays over SSE (reconnect path)
    envelopes = _collect_sse(client, run_id)
    sources = {env["source"] for env in envelopes}
    assert sources == {"prep", "01", "02"}
    bodies_by_source: dict[str, list[dict]] = {"prep": [], "01": [], "02": []}
    for env in envelopes:
        bodies_by_source[env["source"]].append(env["event"])
    # prepare phase ran once and logged
    assert {"t": "log", "level": "info", "msg": "prep-ok"} in bodies_by_source["prep"]
    # each fanned-out video consumed the shared result and produced a result event
    for src in ("01", "02"):
        assert {"t": "log", "level": "info", "msg": "hello from prep"} in bodies_by_source[src]
        assert any(e.get("t") == "result" for e in bodies_by_source[src])

    # the durable record on disk agrees with what the API returned
    run_dir = tmp_path / "runs" / "prepares" / run_id
    assert (run_dir / "request.json").is_file()
    on_disk = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    assert on_disk["status"] == "complete"
    assert (run_dir / "shared" / "result.json").is_file()
