from pathlib import Path

from app.registry.problems import ProblemCode
from app.registry.scan import scan
from tests.registry.fixtures import minimal_toml, problem_codes, write_plugin


def test_scan_returns_both_valid_and_broken_folders_without_crashing(tmp_path: Path) -> None:
    write_plugin(tmp_path, "ok-workflow", minimal_toml("ok-workflow"))
    write_plugin(tmp_path, "broken-workflow", "[[[not toml")
    (tmp_path / "no-manifest").mkdir()

    snapshot = scan(tmp_path)

    names = [entry.folder_name for entry in snapshot]
    assert names == ["broken-workflow", "ok-workflow"]
    by_name = {entry.folder_name: entry for entry in snapshot}
    assert by_name["ok-workflow"].manifest is not None
    assert by_name["ok-workflow"].problems == ()
    assert ProblemCode.MANIFEST_UNREADABLE.value in problem_codes(by_name["broken-workflow"])


def test_scan_orders_by_folder_name(tmp_path: Path) -> None:
    write_plugin(tmp_path, "zeta", minimal_toml("zeta"))
    write_plugin(tmp_path, "alpha", minimal_toml("alpha"))
    snapshot = scan(tmp_path)
    assert [entry.folder_name for entry in snapshot] == ["alpha", "zeta"]


def test_scan_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert scan(tmp_path / "missing") == []
