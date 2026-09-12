"""E-4a contract: list a run's serveable files (the records/replay Artifacts panel, §5.8 / §8).

`GET /api/workflows/{workflow_id}/runs/{run_id}/files` (no trailing path) returns the run's
serveable files as `{"files": [{"path": <run-relative posix>, "size": <bytes>}, ...]}`, so the
records view can enumerate a run's artifacts (script, voice, composition, captions, final.mp4)
without guessing names. It mirrors the file-serving endpoint's confinement: `context.json` is never
listed (it holds injected secrets), and internal dot-directories (`.steps`, `.library-overlay`) are
skipped as run state rather than artifacts. Unknown/unsafe runs 404 like the serving endpoint.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from tests.api.test_runs import _client, _install_stub

WORKFLOW = "succeeds"
RUN_ID = "20240101-000000"


def _seed_run(tmp_path: Path, files: dict[str, bytes]) -> TestClient:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    _install_stub(workflows_dir, WORKFLOW)
    run_dir = tmp_path / "runs" / WORKFLOW / RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    for relative, data in files.items():
        target = run_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return _client(tmp_path)


def _list(client: TestClient) -> dict:
    response = client.get(f"/api/workflows/{WORKFLOW}/runs/{RUN_ID}/files")
    assert response.status_code == 200, response.text
    return response.json()


def test_listing_returns_run_relative_paths_and_sizes(tmp_path: Path) -> None:
    client = _seed_run(
        tmp_path,
        {
            "01/final.mp4": b"x" * 21,
            "01/artifacts/script.md": b"hello",
        },
    )
    body = _list(client)
    by_path = {item["path"]: item["size"] for item in body["files"]}
    assert by_path["01/final.mp4"] == 21
    assert by_path["01/artifacts/script.md"] == 5
    # Paths are run-relative and posix, never absolute.
    assert all(not Path(item["path"]).is_absolute() for item in body["files"])
    assert all("\\" not in item["path"] for item in body["files"])


def test_listing_excludes_context_json(tmp_path: Path) -> None:
    # context.json holds injected secrets and is never served — so it is never listed either.
    client = _seed_run(
        tmp_path,
        {"01/final.mp4": b"v", "01/context.json": b'{"secret":"x"}', "context.json": b"{}"},
    )
    paths = {item["path"] for item in _list(client)["files"]}
    assert not any(p.endswith("context.json") for p in paths)
    assert "01/final.mp4" in paths


def test_listing_excludes_internal_dot_dirs(tmp_path: Path) -> None:
    # .steps / .library-overlay are run state, not artifacts.
    client = _seed_run(
        tmp_path,
        {
            "01/final.mp4": b"v",
            "01/.steps/abc.json": b"{}",
            "01/.library-overlay/x.bin": b"y",
        },
    )
    paths = {item["path"] for item in _list(client)["files"]}
    assert "01/final.mp4" in paths
    assert not any("/.steps/" in p or p.startswith(".steps/") for p in paths)
    assert not any(".library-overlay" in p for p in paths)


def test_listing_empty_run_returns_empty_list(tmp_path: Path) -> None:
    client = _seed_run(tmp_path, {})
    assert _list(client) == {"files": []}


def test_listing_unknown_run_is_404(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, WORKFLOW)
    client = _client(tmp_path)
    response = client.get(f"/api/workflows/{WORKFLOW}/runs/no-such-run/files")
    assert response.status_code == 404


def test_listing_unsafe_run_id_is_404(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, WORKFLOW)
    client = _client(tmp_path)
    response = client.get(f"/api/workflows/{WORKFLOW}/runs/../escape/files")
    assert response.status_code == 404
