from pathlib import Path

import pytest

from app.core.env import EnvBlocked, EnvReady, ensure_env, requirements_hash, venv_python

MARKER = ".requirements.sha256"


def test_venv_python_is_scripts_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    assert venv_python(Path("venvs") / "wf") == Path("venvs") / "wf" / "Scripts" / "python.exe"


def test_venv_python_is_bin_on_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    assert venv_python(Path("venvs") / "wf") == Path("venvs") / "wf" / "bin" / "python"


def _workflow(tmp_path: Path, requirements: str | None = "httpx==2.10.0\n") -> Path:
    workflow_dir = tmp_path / "workflow"
    workflow_dir.mkdir()
    if requirements is not None:
        (workflow_dir / "requirements.txt").write_text(requirements, encoding="utf-8")
    return workflow_dir


def test_unchanged_hash_does_not_invoke_installer(tmp_path: Path) -> None:
    workflow_dir = _workflow(tmp_path)
    venvs_dir = tmp_path / "venvs"
    venv_dir = venvs_dir / "news-explainer"
    venv_dir.mkdir(parents=True)
    (venv_dir / MARKER).write_text(requirements_hash(workflow_dir), encoding="utf-8")
    calls: list[str] = []

    result = ensure_env(
        "news-explainer",
        workflow_dir,
        "3.12",
        venvs_dir=venvs_dir,
        sdk_dir=tmp_path / "sdk",
        find_python=lambda _version: (_ for _ in ()).throw(AssertionError("find_python")),
        create_venv=lambda *_args: calls.append("create"),
        install=lambda *_args: calls.append("install"),
    )
    assert isinstance(result, EnvReady)
    assert result.python == venv_python(venv_dir)
    assert calls == []


def test_changed_hash_invokes_installer_and_stores_hash(tmp_path: Path) -> None:
    workflow_dir = _workflow(tmp_path, "httpx==2.10.0\n")
    venvs_dir = tmp_path / "venvs"
    venv_dir = venvs_dir / "news-explainer"
    venv_dir.mkdir(parents=True)
    (venv_dir / MARKER).write_text("stale-hash", encoding="utf-8")
    interpreter = tmp_path / "python3.12"
    installs: list[tuple[Path, Path, Path | None]] = []

    def create_venv(_python: Path, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)

    def install(venv_py: Path, sdk_dir: Path, requirements: Path | None) -> None:
        installs.append((venv_py, sdk_dir, requirements))

    sdk_dir = tmp_path / "sdk"
    result = ensure_env(
        "news-explainer",
        workflow_dir,
        "3.12",
        venvs_dir=venvs_dir,
        sdk_dir=sdk_dir,
        find_python=lambda version: interpreter if version == "3.12" else None,
        create_venv=create_venv,
        install=install,
    )
    assert isinstance(result, EnvReady)
    assert result.python == venv_python(venv_dir)
    assert len(installs) == 1
    assert installs[0] == (venv_python(venv_dir), sdk_dir, workflow_dir / "requirements.txt")
    assert (venv_dir / MARKER).read_text(encoding="utf-8") == requirements_hash(workflow_dir)


def test_first_run_without_requirements_installs_sdk_only(tmp_path: Path) -> None:
    workflow_dir = _workflow(tmp_path, requirements=None)
    venvs_dir = tmp_path / "venvs"
    interpreter = tmp_path / "python3.12"
    installs: list[Path | None] = []

    def create_venv(_python: Path, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)

    result = ensure_env(
        "news-explainer",
        workflow_dir,
        "3.12",
        venvs_dir=venvs_dir,
        sdk_dir=tmp_path / "sdk",
        find_python=lambda _version: interpreter,
        create_venv=create_venv,
        install=lambda _py, _sdk, requirements: installs.append(requirements),
    )
    assert isinstance(result, EnvReady)
    assert installs == [None]
    assert (venvs_dir / "news-explainer" / MARKER).read_text(encoding="utf-8") == requirements_hash(
        workflow_dir
    )


def test_missing_python_returns_blocked_and_skips_venv(
    tmp_path: Path,
) -> None:
    workflow_dir = _workflow(tmp_path)
    calls: list[str] = []
    result = ensure_env(
        "news-explainer",
        workflow_dir,
        "3.12",
        venvs_dir=tmp_path / "venvs",
        sdk_dir=tmp_path / "sdk",
        find_python=lambda _version: None,
        create_venv=lambda *_args: calls.append("create"),
        install=lambda *_args: calls.append("install"),
    )
    assert isinstance(result, EnvBlocked)
    assert "3.12" in result.reason
    assert "not installed" in result.reason.lower()
    assert calls == []
    assert not (tmp_path / "venvs" / "news-explainer").exists()


def test_failed_install_does_not_store_hash(tmp_path: Path) -> None:
    workflow_dir = _workflow(tmp_path)
    venvs_dir = tmp_path / "venvs"

    def create_venv(_python: Path, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)

    def install(_venv_py: Path, _sdk_dir: Path, _requirements: Path | None) -> None:
        raise RuntimeError("pip failed")

    with pytest.raises(RuntimeError, match="pip failed"):
        ensure_env(
            "news-explainer",
            workflow_dir,
            "3.12",
            venvs_dir=venvs_dir,
            sdk_dir=tmp_path / "sdk",
            find_python=lambda _version: tmp_path / "python3.12",
            create_venv=create_venv,
            install=install,
        )
    assert not (venvs_dir / "news-explainer" / MARKER).exists()


def test_ensure_env_rejects_unsafe_workflow_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        ensure_env("../secret", tmp_path, "3.12", venvs_dir=tmp_path / "venvs")
