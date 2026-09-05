"""S2a contract: least-privilege secret injection + passphrase never reaches a subprocess.

At app start the §5.6 store is loaded (`create_app(secrets=...)` / `SFVF_SECRETS_PASSPHRASE`).
Each run's `context.json` receives ONLY the secrets the workflow declares it needs via the
manifest `[[requires_keys]]` allowlist — never the whole store (least privilege). The master
passphrase is stripped from EVERY child process the app spawns: the workflow runner AND the
env-setup / `pip install` subprocesses (HARDENING H17), via the shared
`app.core.secrets.subprocess_env()`. All fake values live only under tmp_path.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.core.env as env_mod
import app.core.supervisor as supervisor_mod
from app.core.env import EnvReady
from app.core.secrets import SecretStore, subprocess_env
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


def _client(tmp_path: Path, *, secrets: object = None, popen: object = None) -> TestClient:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    return TestClient(
        create_app(
            workflows_dir=workflows_dir,
            runs_dir=tmp_path / "runs",
            ensure_env=_ready,  # type: ignore[arg-type]
            secrets=secrets,  # type: ignore[arg-type]
            popen=popen,  # type: ignore[arg-type]
        )
    )


def _capture_context_secrets(records: list):
    # Capture each spawned runner's context.json secrets AT SPAWN — before S2b scrubs them
    # post-run — then delegate to the real Popen so the stub still runs to completion.
    def popen(command, **kwargs):
        try:
            idx = command.index("--context")
            data = json.loads(Path(command[idx + 1]).read_text(encoding="utf-8"))
            records.append(data.get("secrets"))
        except (ValueError, OSError, IndexError):
            records.append(None)
        return subprocess.Popen(command, **kwargs)

    return popen


def _wait_terminal(client: TestClient, run_id: str, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/api/workflows/succeeds/runs/{run_id}")
        if r.status_code == 200 and r.json()["status"] in TERMINAL:
            return
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not reach a terminal status")


def _injected_secrets_at_spawn(
    tmp_path: Path, *, secrets: object, requires_keys: list[str] | None
) -> dict:
    # Verify injection by what the runner actually received in context.json AT SPAWN — S2b
    # scrubs those secrets from the on-disk file after the run, so a post-run read would be {}.
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    _install_stub(workflows_dir, "succeeds", requires_keys=requires_keys)
    records: list = []
    client = _client(tmp_path, secrets=secrets, popen=_capture_context_secrets(records))
    r = client.post(
        "/api/workflows/succeeds/runs",
        json={"params": {"topic": "a"}, "video_count": 1, "concurrency": 1},
    )
    assert r.status_code == 202
    _wait_terminal(client, r.json()["run_id"])
    assert records, "the runner was never spawned"
    return records[0] or {}


def test_only_allowlisted_secrets_are_injected(tmp_path):
    # The workflow declares it needs OPENROUTER_API_KEY; HIGGSFIELD_API_KEY is withheld.
    injected = _injected_secrets_at_spawn(
        tmp_path,
        secrets={"OPENROUTER_API_KEY": "sk-or", "HIGGSFIELD_API_KEY": "hf-secret"},
        requires_keys=["OPENROUTER_API_KEY"],
    )
    assert injected == {"OPENROUTER_API_KEY": "sk-or"}


def test_no_required_keys_injects_empty(tmp_path):
    # A workflow that declares no keys receives none, even when the store is populated.
    injected = _injected_secrets_at_spawn(
        tmp_path,
        secrets={"OPENROUTER_API_KEY": "sk-or"},
        requires_keys=None,
    )
    assert injected == {}


def test_subprocess_env_strips_the_master_passphrase(monkeypatch):
    monkeypatch.setenv("SFVF_SECRETS_PASSPHRASE", "top-secret-passphrase")
    monkeypatch.setenv("SFVF_MARKER_KEEP", "keep-me")
    env = subprocess_env()
    assert "SFVF_SECRETS_PASSPHRASE" not in env
    assert env.get("SFVF_MARKER_KEEP") == "keep-me"  # other env is still inherited


def test_env_setup_subprocess_does_not_inherit_passphrase(monkeypatch):
    # H17: pip install / venv setup (env._run_timed) must not leak the master passphrase to
    # workflow-declared dependency build code.
    monkeypatch.setenv("SFVF_SECRETS_PASSPHRASE", "top-secret-passphrase")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)

        class _Done:
            returncode = 0

        return _Done()

    monkeypatch.setattr(env_mod.subprocess, "run", fake_run)
    env_mod._run_timed(["python", "-c", "pass"])
    assert "env" in captured
    assert "SFVF_SECRETS_PASSPHRASE" not in captured["env"]  # type: ignore[operator]


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
