"""S2b contract: injected secrets must not be exposed after S2a put them in context.json.

Two vectors closed:
1. The run-file download endpoint must NEVER serve a `context.json` (it carries the allowlisted
   secrets) — any request for one returns 404, while other run files still download.
2. After the workflow subprocess has consumed its `context.json`, the on-disk copy is scrubbed
   (`secrets` emptied) so the keys don't persist in the run directory.

Fake values live only under tmp_path.
"""

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
def _clear_supervisor_state():
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


def _install_stub(
    workflows_dir: Path, name: str, *, requires_keys: list[str] | None = None
) -> None:
    dest = workflows_dir / name
    shutil.copytree(STUBS / name, dest)
    (dest / "requirements.txt").write_text("", encoding="utf-8")
    if requires_keys:
        toml = dest / "workflow.toml"
        extra = "".join(
            f'\n[[requires_keys]]\nname = "{k}"\nlabel = "{k}"\n' for k in requires_keys
        )
        toml.write_text(toml.read_text(encoding="utf-8") + extra, encoding="utf-8")


def _client(tmp_path: Path, *, secrets: object = None) -> TestClient:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    return TestClient(
        create_app(
            workflows_dir=workflows_dir,
            runs_dir=tmp_path / "runs",
            ensure_env=_ready,  # type: ignore[arg-type]
            secrets=secrets,  # type: ignore[arg-type]
        )
    )


def _wait_terminal(client: TestClient, run_id: str, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/api/workflows/succeeds/runs/{run_id}")
        if r.status_code == 200 and r.json()["status"] in TERMINAL:
            return
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not reach a terminal status")


def test_context_json_is_not_downloadable(tmp_path):
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    client = _client(tmp_path)
    # A run dir with a context.json (secret-bearing) and an ordinary artifact.
    run_dir = tmp_path / "runs" / "succeeds" / "20260101-000000" / "shared"
    run_dir.mkdir(parents=True)
    (run_dir / "context.json").write_text('{"secrets": {"OPENROUTER_API_KEY": "sk-x"}}', "utf-8")
    (run_dir / "note.txt").write_text("ordinary", "utf-8")

    base = "/api/workflows/succeeds/runs/20260101-000000/files/shared"
    assert client.get(f"{base}/context.json").status_code == 404  # secret file blocked
    assert client.get(f"{base}/note.txt").status_code == 200  # ordinary file still served


def test_context_json_secrets_are_scrubbed_after_run(tmp_path):
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds", requires_keys=["OPENROUTER_API_KEY"])
    client = _client(tmp_path, secrets={"OPENROUTER_API_KEY": "sk-secret-value"})
    r = client.post(
        "/api/workflows/succeeds/runs",
        json={"params": {"topic": "a"}, "video_count": 1, "concurrency": 1},
    )
    assert r.status_code == 202
    _wait_terminal(client, r.json()["run_id"])

    contexts = list((tmp_path / "runs").rglob("context.json"))
    assert contexts, "no context.json was written"
    for ctx_path in contexts:
        data = json.loads(ctx_path.read_text(encoding="utf-8"))
        assert data.get("secrets") == {}, f"secrets not scrubbed in {ctx_path}"
        # and the raw value is gone from disk
        assert "sk-secret-value" not in ctx_path.read_text(encoding="utf-8")
