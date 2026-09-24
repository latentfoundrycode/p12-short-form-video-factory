"""PKG-2 contract: runtime data lives under a relocatable DATA_ROOT, not the install folder.

For an installed SFVF, program files sit under `%LOCALAPPDATA%\\Programs\\SFVF` and are REPLACED on
upgrade — so run history, the library, the money ledger, the SecretStore, and schedules must live
elsewhere (`%LOCALAPPDATA%\\SFVF`) or an upgrade would wipe them. `app.paths.DATA_ROOT` is that
root: `$SFVF_DATA_DIR` when set, else `APP_ROOT` (so dev is unchanged until the installer sets the
variable). All runtime-generated data (runs, cache, library, venvs) and user state (secrets,
schedules, budget ledger) hang off `DATA_ROOT`; shipped program dirs (workflows, web, sdk) stay
under `APP_ROOT`.

The relocation test reloads the path-owning modules with the env set (module constants are read once
at import — correct, as the installer sets the variable before launch — so a reload is how a test
exercises it), and restores them afterward. No network, no spend.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import app.core.budget_config as budget_config
import app.core.schedules as schedules
import app.core.secrets as secrets
import app.paths as paths


def test_default_data_root_is_app_root() -> None:
    # With SFVF_DATA_DIR unset (the test env), data stays under the repo root — no dev change.
    assert paths.DATA_ROOT == paths.APP_ROOT


def test_data_dirs_hang_off_data_root_program_dirs_off_app_root() -> None:
    assert paths.RUNS_DIR == paths.DATA_ROOT / "runs"
    assert paths.CACHE_DIR == paths.DATA_ROOT / "cache"
    assert paths.LIBRARY_DIR == paths.DATA_ROOT / "library"
    assert paths.VENVS_DIR == paths.DATA_ROOT / "venvs"
    # Shipped program files are NOT data — they stay under the install root, replaced on upgrade.
    assert paths.WORKFLOWS_DIR == paths.APP_ROOT / "workflows"
    assert paths.WEB_DIR == paths.APP_ROOT / "app" / "web"
    assert paths.SDK_DIR == paths.APP_ROOT / "sdk"


def test_secrets_and_schedules_defaults_hang_off_data_root() -> None:
    assert secrets._DEFAULT_STORE == paths.DATA_ROOT / "secrets.enc"
    assert schedules.SCHEDULES_PATH == paths.DATA_ROOT / "schedules.json"


def _reload_paths_modules() -> None:
    importlib.reload(paths)
    importlib.reload(secrets)
    importlib.reload(schedules)
    importlib.reload(budget_config)


def test_sfvf_data_dir_relocates_all_runtime_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "appdata" / "SFVF"
    monkeypatch.setenv("SFVF_DATA_DIR", str(data))
    monkeypatch.delenv("SFVF_BUDGET_STATE", raising=False)
    config = tmp_path / "budget.toml"
    config.write_text("[openrouter]\nper_run = 1.0\n", encoding="utf-8")
    monkeypatch.setenv("SFVF_BUDGET_CONFIG", str(config))
    try:
        _reload_paths_modules()
        resolved = data.resolve()
        assert resolved == paths.DATA_ROOT
        # Every data location moved under the new root...
        assert resolved / "runs" == paths.RUNS_DIR
        assert resolved / "cache" == paths.CACHE_DIR
        assert resolved / "library" == paths.LIBRARY_DIR
        assert resolved / "venvs" == paths.VENVS_DIR
        assert resolved / "secrets.enc" == secrets._DEFAULT_STORE
        assert resolved / "schedules.json" == schedules.SCHEDULES_PATH
        ledger = budget_config.load_budget_config().ledger_path  # type: ignore[union-attr]
        assert ledger == (resolved / "state" / "budget" / "ledger.jsonl").resolve()
        # ...while shipped program dirs did NOT move.
        assert paths.WORKFLOWS_DIR == paths.APP_ROOT / "workflows"
        assert paths.SDK_DIR == paths.APP_ROOT / "sdk"
    finally:
        monkeypatch.delenv("SFVF_DATA_DIR", raising=False)
        _reload_paths_modules()  # restore module constants for the rest of the suite
    assert paths.DATA_ROOT == paths.APP_ROOT  # restored
    assert paths.RUNS_DIR == paths.APP_ROOT / "runs"
