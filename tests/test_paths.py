from pathlib import Path

from app.paths import (
    APP_ROOT,
    RUNS_DIR,
    SDK_DIR,
    VENVS_DIR,
    WORKFLOWS_DIR,
    is_safe_path_segment,
    safe_join,
)


def test_app_root_is_the_repository_root() -> None:
    assert (APP_ROOT / "app" / "__init__.py").is_file()
    assert (APP_ROOT / "docs").is_dir()


def test_workflows_dir_is_under_app_root() -> None:
    assert WORKFLOWS_DIR == APP_ROOT / "workflows"


def test_runs_dir_is_under_app_root() -> None:
    assert RUNS_DIR == APP_ROOT / "runs"


def test_venvs_dir_is_under_app_root() -> None:
    assert VENVS_DIR == APP_ROOT / "venvs"


def test_sdk_dir_is_under_app_root() -> None:
    assert SDK_DIR == APP_ROOT / "sdk"


def test_is_safe_path_segment_rejects_traversal() -> None:
    assert is_safe_path_segment("news-explainer")
    assert not is_safe_path_segment("")
    assert not is_safe_path_segment("..")
    assert not is_safe_path_segment("../secret")
    assert not is_safe_path_segment("..\\secret")
    assert not is_safe_path_segment("/etc/passwd")


def test_is_safe_path_segment_rejects_windows_drive_relative() -> None:
    # `runs_dir / "C:"` resets to the C: drive root on Windows (drive-relative), escaping the base.
    # Any segment carrying a drive / colon must be rejected.
    for bad in ("C:", "D:", "c:", "C:foo", "a:b", "::"):
        assert not is_safe_path_segment(bad), bad
    # legitimate ids (workflow folder names, run ids) are unaffected
    assert is_safe_path_segment("20260927-000001")
    assert is_safe_path_segment("sensational-science-news")


def test_safe_join_stays_inside_folder(tmp_path: Path) -> None:
    folder = tmp_path / "wf"
    folder.mkdir()
    assert safe_join(folder, "thumbnail.png") == folder / "thumbnail.png"
    assert safe_join(folder, "../secret.png") is None
    assert safe_join(folder, "/tmp/secret.png") is None
