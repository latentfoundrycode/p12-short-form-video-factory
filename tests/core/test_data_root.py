"""PKG-2 contract: runtime data lives under a relocatable DATA_ROOT, not the install folder.

For an installed SFVF, program files sit under `%LOCALAPPDATA%\\Programs\\SFVF` and are REPLACED on
upgrade — so run history, the library, the money ledger, the SecretStore, and schedules must live
elsewhere (`%LOCALAPPDATA%\\SFVF`) or an upgrade would wipe them. `app.paths.DATA_ROOT` is that
root: `$SFVF_DATA_DIR` when set, else `APP_ROOT` (so dev is unchanged until the installer sets the
variable). All runtime-generated data (runs, cache, library, venvs) and user state (secrets,
schedules, budget ledger) hang off `DATA_ROOT`; shipped program dirs (workflows, web, sdk) stay
under `APP_ROOT`.

`DATA_ROOT` is a module constant read once at import — correct, since the installer sets the
variable before launching the server. So the contract exercises it in a **fresh interpreter** (a
subprocess with the env set), never `importlib.reload` in-process: reloading would re-stamp the
constants but also swap class objects (SecretsError/ScheduleEntry), breaking `pytest.raises`/model
identity in the rest of the suite and tempting a production-side reload hack. No network, no spend.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from app.paths import APP_ROOT

_PROBE = """
import json
import app.paths as p
import app.core.secrets as s
import app.core.schedules as sc
import app.core.budget_config as b
cfg = b.load_budget_config()
print(json.dumps({
    "DATA_ROOT": str(p.DATA_ROOT),
    "APP_ROOT": str(p.APP_ROOT),
    "RUNS_DIR": str(p.RUNS_DIR),
    "CACHE_DIR": str(p.CACHE_DIR),
    "LIBRARY_DIR": str(p.LIBRARY_DIR),
    "VENVS_DIR": str(p.VENVS_DIR),
    "WORKFLOWS_DIR": str(p.WORKFLOWS_DIR),
    "SDK_DIR": str(p.SDK_DIR),
    "SECRETS": str(s._DEFAULT_STORE),
    "SCHEDULES": str(sc.SCHEDULES_PATH),
    "LEDGER": str(cfg.ledger_path),
}))
"""


def _resolved_paths(tmp_path: Path, *, data_dir: str | None) -> dict[str, str]:
    """Resolve SFVF's paths in a fresh interpreter with (or without) SFVF_DATA_DIR set."""
    env = {k: v for k, v in os.environ.items() if k not in {"SFVF_DATA_DIR", "SFVF_BUDGET_STATE"}}
    if data_dir is not None:
        env["SFVF_DATA_DIR"] = data_dir
    config = tmp_path / "budget.toml"
    config.write_text("[openrouter]\nper_run = 1.0\n", encoding="utf-8")
    env["SFVF_BUDGET_CONFIG"] = str(config)  # so load_budget_config returns a config, not None
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=APP_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_default_data_root_is_app_root(tmp_path: Path) -> None:
    # With SFVF_DATA_DIR unset, data stays under the repo root — no dev/behaviour change.
    p = _resolved_paths(tmp_path, data_dir=None)
    assert p["DATA_ROOT"] == p["APP_ROOT"]
    assert p["RUNS_DIR"] == str(Path(p["APP_ROOT"]) / "runs")
    assert p["SECRETS"] == str(Path(p["APP_ROOT"]) / "secrets.enc")
    assert p["SCHEDULES"] == str(Path(p["APP_ROOT"]) / "schedules.json")


def test_sfvf_data_dir_relocates_all_runtime_data(tmp_path: Path) -> None:
    data = tmp_path / "appdata" / "SFVF"
    p = _resolved_paths(tmp_path, data_dir=str(data))
    root = str(data.resolve())
    assert p["DATA_ROOT"] == root
    # Every data location moved under the new root...
    assert p["RUNS_DIR"] == str(Path(root) / "runs")
    assert p["CACHE_DIR"] == str(Path(root) / "cache")
    assert p["LIBRARY_DIR"] == str(Path(root) / "library")
    assert p["VENVS_DIR"] == str(Path(root) / "venvs")
    assert p["SECRETS"] == str(Path(root) / "secrets.enc")
    assert p["SCHEDULES"] == str(Path(root) / "schedules.json")
    assert p["LEDGER"] == str((Path(root) / "state" / "budget" / "ledger.jsonl").resolve())
    # ...while shipped program dirs did NOT move (still under the install root).
    assert p["WORKFLOWS_DIR"] == str(Path(p["APP_ROOT"]) / "workflows")
    assert p["SDK_DIR"] == str(Path(p["APP_ROOT"]) / "sdk")
    assert p["APP_ROOT"] != root  # the install root and the data root are genuinely distinct here


def test_program_dirs_are_not_under_data_root() -> None:
    # A pure in-process check (no env, no reload): program dirs are APP_ROOT-relative.
    from app import paths

    assert paths.WORKFLOWS_DIR == paths.APP_ROOT / "workflows"
    assert paths.WEB_DIR == paths.APP_ROOT / "app" / "web"
    assert paths.SDK_DIR == paths.APP_ROOT / "sdk"
    assert paths.RUNS_DIR == paths.DATA_ROOT / "runs"  # data dir hangs off DATA_ROOT
