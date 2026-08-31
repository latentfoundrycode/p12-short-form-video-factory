from pathlib import Path

from fastapi.testclient import TestClient

from tests.api.test_runs import _client, _install_stub

PAYLOAD = b"0123456789ABCDEFGHIJ"  # 20 bytes


def _seed_run_file(
    tmp_path: Path,
    *,
    workflow_id: str = "succeeds",
    run_id: str = "20240101-000000",
    relative: str = "final.bin",
    data: bytes = PAYLOAD,
) -> tuple[TestClient, str]:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    _install_stub(workflows_dir, workflow_id)
    run_dir = tmp_path / "runs" / workflow_id / run_id
    target = run_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    client = _client(tmp_path)
    url = f"/api/workflows/{workflow_id}/runs/{run_id}/files/{relative}"
    return client, url


def test_full_get_returns_body_and_accept_ranges(tmp_path: Path) -> None:
    client, url = _seed_run_file(tmp_path)
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == PAYLOAD
    assert response.headers.get("accept-ranges") == "bytes"


def test_range_get_returns_206_slice(tmp_path: Path) -> None:
    client, url = _seed_run_file(tmp_path)
    response = client.get(url, headers={"Range": "bytes=10-19"})
    assert response.status_code == 206
    assert response.headers.get("content-range") == f"bytes 10-19/{len(PAYLOAD)}"
    assert response.content == PAYLOAD[10:20]


def test_nested_path_served(tmp_path: Path) -> None:
    nested = b"nested-script-body"
    client, url = _seed_run_file(
        tmp_path,
        relative="01/artifacts/script.md",
        data=nested,
    )
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == nested


def test_traversal_blocked(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    run_id = "20240101-000000"
    run_dir = tmp_path / "runs" / "succeeds" / run_id
    run_dir.mkdir(parents=True)
    secret = tmp_path / "secret.txt"
    secret.write_text("should-not-leak", encoding="utf-8")
    client = _client(tmp_path)

    for relative in ("../../secret.txt", "01/../../secret.txt", "../secret.txt"):
        response = client.get(f"/api/workflows/succeeds/runs/{run_id}/files/{relative}")
        assert response.status_code == 404, relative
        assert "should-not-leak" not in response.text


def test_missing_file_is_404(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    run_id = "20240101-000000"
    (tmp_path / "runs" / "succeeds" / run_id).mkdir(parents=True)
    client = _client(tmp_path)
    response = client.get(f"/api/workflows/succeeds/runs/{run_id}/files/missing.bin")
    assert response.status_code == 404


def test_unknown_run_is_404(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    client = _client(tmp_path)
    response = client.get("/api/workflows/succeeds/runs/no-such-run/files/final.bin")
    assert response.status_code == 404


def test_unsafe_run_id_is_404(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    client = _client(tmp_path)
    response = client.get("/api/workflows/succeeds/runs/../escape/files/final.bin")
    assert response.status_code == 404
