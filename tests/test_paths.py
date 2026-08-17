from app.paths import APP_ROOT, WORKFLOWS_DIR


def test_app_root_is_the_repository_root() -> None:
    assert (APP_ROOT / "app" / "__init__.py").is_file()
    assert (APP_ROOT / "docs").is_dir()


def test_workflows_dir_is_under_app_root() -> None:
    assert WORKFLOWS_DIR == APP_ROOT / "workflows"
