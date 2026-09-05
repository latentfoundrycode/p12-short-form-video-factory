"""T2b-2a contract: activate the budget gate — load a budget file and inject it into context.json.

The T2b-1 SDK gate is inert until the supervisor feeds it config. This loads a TOML budget file
(gated by SFVF_BUDGET_CONFIG, as the secret store is gated by SFVF_SECRETS_PASSPHRASE), builds a
`sfvf.context.BudgetConfig`, and writes it into every run's context.json so the child enforces the
ceilings/kill-switch before any paid call. No env / no file → no budget (the gate stays inert). A
misconfigured env (missing or malformed file) fails closed (raises) rather than running ungated. All
fake ceilings/paths live only under tmp_path; no real spend, no network.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sfvf.context import BudgetConfig

import app.core.supervisor as supervisor_mod
from app.core.budget_config import BudgetConfigError, load_budget_config
from app.core.env import EnvReady
from app.main import create_app

STUBS = Path(__file__).resolve().parent.parent / "stubs"
TERMINAL = {"complete", "partial", "stopped", "stopped-budget", "failed"}

_TOML = """
[openrouter]
per_run = 0.50
per_day = 2.00
estimate = 0.05

[higgsfield]
per_run = 100
per_day = 300
estimate = 50
"""


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


@pytest.fixture(autouse=True)
def _clear_budget_env(monkeypatch):
    # Every test states its own budget env explicitly; never inherit the machine's.
    monkeypatch.delenv("SFVF_BUDGET_CONFIG", raising=False)
    monkeypatch.delenv("SFVF_BUDGET_STATE", raising=False)


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def _write_toml(tmp_path: Path) -> Path:
    p = tmp_path / "budget.toml"
    p.write_text(_TOML, encoding="utf-8")
    return p


def _install_stub(workflows_dir: Path, name: str) -> None:
    dest = workflows_dir / name
    shutil.copytree(STUBS / name, dest)
    (dest / "requirements.txt").write_text("", encoding="utf-8")


def _capture_context_budget(records: list) -> object:
    # Capture each spawned runner's context.json `budget` block AT SPAWN, then delegate to the real
    # Popen so the stub still runs to completion.
    def popen(command, **kwargs):
        try:
            idx = command.index("--context")
            data = json.loads(Path(command[idx + 1]).read_text(encoding="utf-8"))
            records.append(data.get("budget"))
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


def _budget_at_spawn(tmp_path: Path) -> object:
    # Capture the runner's context.json `budget` block at spawn. The env (set or not by the caller)
    # decides whether that block is present; the capturing popen writes into the same `records` list
    # this helper reads back.
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    _install_stub(workflows_dir, "succeeds")
    records: list = []
    client = TestClient(
        create_app(
            workflows_dir=workflows_dir,
            runs_dir=tmp_path / "runs",
            ensure_env=_ready,  # type: ignore[arg-type]
            popen=_capture_context_budget(records),  # type: ignore[arg-type]
        )
    )
    r = client.post(
        "/api/workflows/succeeds/runs",
        json={"params": {"topic": "a"}, "video_count": 1, "concurrency": 1},
    )
    assert r.status_code == 202
    _wait_terminal(client, r.json()["run_id"])
    assert records, "the runner was never spawned"
    return records[0]


# --- loader ---


def test_load_without_env_returns_none():
    assert load_budget_config() is None


def test_load_parses_ceilings_estimates_and_derives_paths(tmp_path, monkeypatch):
    cfg_path = _write_toml(tmp_path)
    state = tmp_path / "state"
    monkeypatch.setenv("SFVF_BUDGET_CONFIG", str(cfg_path))
    monkeypatch.setenv("SFVF_BUDGET_STATE", str(state))
    cfg = load_budget_config()
    assert isinstance(cfg, BudgetConfig)
    assert cfg.per_run == {"openrouter": 0.50, "higgsfield": 100.0}
    assert cfg.per_day == {"openrouter": 2.00, "higgsfield": 300.0}
    assert cfg.estimates == {"openrouter": 0.05, "higgsfield": 50.0}
    assert cfg.ledger_path.is_absolute()
    assert cfg.kill_switch_path is not None and cfg.kill_switch_path.is_absolute()
    # ledger + kill-switch live under the configured state dir
    assert state in cfg.ledger_path.parents
    assert state in cfg.kill_switch_path.parents


def test_load_missing_file_when_env_set_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("SFVF_BUDGET_CONFIG", str(tmp_path / "does-not-exist.toml"))
    with pytest.raises(BudgetConfigError):
        load_budget_config()


def test_load_malformed_toml_fails_closed(tmp_path, monkeypatch):
    bad = tmp_path / "budget.toml"
    bad.write_text("this is = = not valid toml", encoding="utf-8")
    monkeypatch.setenv("SFVF_BUDGET_CONFIG", str(bad))
    with pytest.raises(BudgetConfigError):
        load_budget_config()


# --- create_app wiring ---


def test_create_app_loads_budget_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SFVF_BUDGET_CONFIG", str(_write_toml(tmp_path)))
    monkeypatch.setenv("SFVF_BUDGET_STATE", str(tmp_path / "state"))
    application = create_app(
        workflows_dir=tmp_path / "workflows",
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,  # type: ignore[arg-type]
    )
    assert isinstance(application.state.budget, BudgetConfig)
    assert application.state.budget.per_run["openrouter"] == 0.50


def test_create_app_without_env_budget_is_none(tmp_path):
    application = create_app(
        workflows_dir=tmp_path / "workflows",
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,  # type: ignore[arg-type]
    )
    assert application.state.budget is None


# --- injection into context.json at spawn ---


def test_budget_is_injected_into_context_json(tmp_path, monkeypatch):
    monkeypatch.setenv("SFVF_BUDGET_CONFIG", str(_write_toml(tmp_path)))
    monkeypatch.setenv("SFVF_BUDGET_STATE", str(tmp_path / "state"))
    budget = _budget_at_spawn(tmp_path)
    assert isinstance(budget, dict), "context.json carried no budget block"
    assert budget["per_run"]["openrouter"] == 0.50
    assert budget["per_day"]["openrouter"] == 2.00
    assert budget["estimates"]["openrouter"] == 0.05
    assert budget["ledger_path"]  # a non-empty path string
    assert budget["kill_switch_path"]


def test_no_budget_config_leaves_context_budget_absent(tmp_path):
    # No SFVF_BUDGET_CONFIG (cleared by fixture) → the run's context.json carries no budget block,
    # so the SDK gate stays inert exactly as before T2b-2a.
    budget = _budget_at_spawn(tmp_path)
    assert budget is None
