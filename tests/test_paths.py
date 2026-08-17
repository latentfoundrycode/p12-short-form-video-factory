from pathlib import Path

from app.paths import APP_ROOT, RUNS_DIR, WORKFLOWS_DIR, is_safe_path_segment, safe_join


def test_app_root_is_the_repository_root() -> None:
    assert (APP_ROOT / "app" / "__init__.py").is_file()
    assert (APP_ROOT / "docs").is_dir()


def test_workflows_dir_is_under_app_root() -> None:
    assert WORKFLOWS_DIR == APP_ROOT / "workflows"


def test_runs_dir_is_under_app_root() -> None:
    assert RUNS_DIR == APP_ROOT / "runs"


def test_is_safe_path_segment_rejects_traversal() -> None:
    assert is_safe_path_segment("news-explainer")
    assert not is_safe_path_segment("")
    assert not is_safe_path_segment("..")
    assert not is_safe_path_segment("../secret")
    assert not is_safe_path_segment("..\\secret")
    assert not is_safe_path_segment("/etc/passwd")


def test_safe_join_stays_inside_folder(tmp_path: Path) -> None:
    folder = tmp_path / "wf"
    folder.mkdir()
    assert safe_join(folder, "thumbnail.png") == folder / "thumbnail.png"
    assert safe_join(folder, "../secret.png") is None
    assert safe_join(folder, "/tmp/secret.png") is None
