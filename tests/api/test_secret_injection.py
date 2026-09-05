"""S2a contract: load the §5.6 secret store at app start, inject permitted secrets into every
`context.json`, and never leak the master passphrase to workflow subprocesses (HARDENING H17).

`create_app(..., secrets=...)` accepts an injected mapping (tests use it); when omitted it loads the
`SecretStore` from `SFVF_SECRETS_PASSPHRASE` + `SFVF_SECRETS_PATH` (empty when the passphrase is
unset, so dry runs need no store). The loaded secrets are written into each run's `context.json`
(the transient hand-off the workflow subprocess reads — §5.6), and `_subprocess_env()` strips
`SFVF_SECRETS_PASSPHRASE` from the child environment so the master passphrase never reaches a
workflow. All fake values here live only under tmp_path.
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
from app.core.secrets import SecretStore
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


def _install_stub(workflows_dir: Path, name: str) -> None:
    dest = workflows_dir / name
    shutil.copytree(STUBS / name, dest)
    (dest / "requirements.txt").write_text("", encoding="utf-8")


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


def _run_and_read_context(tmp_path: Path, secrets: object) -> dict:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    _install_stub(workflows_dir, "succeeds")
    client = _client(tmp_path, secrets=secrets)
    r = client.post(
        "/api/workflows/succeeds/runs",
        json={"params": {"topic": "a"}, "video_count": 1, "concurrency": 1},
    )
    assert r.status_code == 202
    _wait_terminal(client, r.json()["run_id"])
    contexts = list((tmp_path / "runs").rglob("context.json"))
    assert contexts, "no context.json was written"
    return json.loads(contexts[0].read_text(encoding="utf-8"))


def test_loaded_secrets_are_injected_into_context(tmp_path):
    ctx = _run_and_read_context(tmp_path, {"OPENROUTER_API_KEY": "sk-inject-test"})
    assert ctx["secrets"] == {"OPENROUTER_API_KEY": "sk-inject-test"}


def test_no_secrets_injects_empty_mapping(tmp_path):
    ctx = _run_and_read_context(tmp_path, None)
    assert ctx["secrets"] == {}


def test_subprocess_env_strips_the_master_passphrase(monkeypatch):
    # H17: the workflow subprocess must never inherit SFVF_SECRETS_PASSPHRASE.
    monkeypatch.setenv("SFVF_SECRETS_PASSPHRASE", "top-secret-passphrase")
    monkeypatch.setenv("SFVF_MARKER_KEEP", "keep-me")
    from app.core.supervisor import _subprocess_env

    env = _subprocess_env()
    assert "SFVF_SECRETS_PASSPHRASE" not in env
    assert env.get("SFVF_MARKER_KEEP") == "keep-me"  # other env is still inherited


def test_create_app_loads_store_when_passphrase_set(tmp_path, monkeypatch):
    path = tmp_path / "secrets.enc"
    SecretStore(path, passphrase="pw").set("HIGGSFIELD_API_KEY", "hf-x")
    monkeypatch.setenv("SFVF_SECRETS_PASSPHRASE", "pw")
    monkeypatch.setenv("SFVF_SECRETS_PATH", str(path))
    application = create_app(
        workflows_dir=tmp_path / "workflows",
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,  # type: ignore[arg-type]
    )
    assert dict(application.state.secrets) == {"HIGGSFIELD_API_KEY": "hf-x"}


def test_create_app_no_passphrase_is_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("SFVF_SECRETS_PASSPHRASE", raising=False)
    application = create_app(
        workflows_dir=tmp_path / "workflows",
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,  # type: ignore[arg-type]
    )
    assert dict(application.state.secrets) == {}
