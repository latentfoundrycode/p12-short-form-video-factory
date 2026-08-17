from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.ids import allocate_run
from app.paths import APP_ROOT, RUNS_DIR


def test_runs_dir_is_under_app_root() -> None:
    assert RUNS_DIR == APP_ROOT / "runs"


def test_allocate_run_uses_utc_yyyymmdd_hhmmss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen = datetime(2026, 8, 10, 14, 30, 22, tzinfo=UTC)
    monkeypatch.setattr("app.core.ids.utc_now", lambda: frozen)
    run_id, path = allocate_run("news-explainer", runs_dir=tmp_path)
    assert run_id == "20260810-143022"
    assert path == tmp_path / "news-explainer" / "20260810-143022"
    assert path.is_dir()


def test_allocate_run_appends_letter_on_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen = datetime(2026, 8, 10, 14, 30, 22, tzinfo=UTC)
    monkeypatch.setattr("app.core.ids.utc_now", lambda: frozen)
    (tmp_path / "news-explainer" / "20260810-143022").mkdir(parents=True)
    (tmp_path / "news-explainer" / "20260810-143022A").mkdir()
    run_id, path = allocate_run("news-explainer", runs_dir=tmp_path)
    assert run_id == "20260810-143022B"
    assert path == tmp_path / "news-explainer" / "20260810-143022B"
    assert path.is_dir()


def test_allocate_run_raises_when_suffixes_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen = datetime(2026, 8, 10, 14, 30, 22, tzinfo=UTC)
    monkeypatch.setattr("app.core.ids.utc_now", lambda: frozen)
    parent = tmp_path / "news-explainer"
    parent.mkdir()
    (parent / "20260810-143022").mkdir()
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        (parent / f"20260810-143022{letter}").mkdir()
    with pytest.raises(RuntimeError, match="exhausted"):
        allocate_run("news-explainer", runs_dir=tmp_path)


@pytest.mark.parametrize("unsafe", ["../secret", "..", "a/b", "a\\b", ""])
def test_allocate_run_rejects_unsafe_workflow_id(tmp_path: Path, unsafe: str) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        allocate_run(unsafe, runs_dir=tmp_path)
