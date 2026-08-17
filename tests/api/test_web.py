from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_serves_spa_and_does_not_shadow_api(tmp_path: Path) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>sfvf</title>\n", encoding="utf-8")
    (web / "asset.txt").write_text("asset-body\n", encoding="utf-8")
    client = TestClient(create_app(workflows_dir=tmp_path, web_dir=web))

    index = client.get("/")
    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]
    assert "sfvf" in index.text

    asset = client.get("/asset.txt")
    assert asset.status_code == 200
    assert "asset-body" in asset.text

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"ok": True}

    workflows = client.get("/api/workflows")
    assert workflows.status_code == 200
    assert workflows.json() == {"workflows": []}

    missing_api = client.get("/api/does-not-exist")
    assert missing_api.status_code == 404
    assert "sfvf" not in missing_api.text


def test_skips_mount_when_index_html_absent(tmp_path: Path) -> None:
    web = tmp_path / "web"
    web.mkdir()
    client = TestClient(create_app(workflows_dir=tmp_path, web_dir=web))
    assert client.get("/api/health").json() == {"ok": True}
    assert client.get("/api/workflows").json() == {"workflows": []}
    assert client.get("/").status_code == 404


def test_skips_mount_when_web_dir_missing(tmp_path: Path) -> None:
    client = TestClient(create_app(workflows_dir=tmp_path, web_dir=tmp_path / "no-web"))
    assert client.get("/api/health").json() == {"ok": True}
    assert client.get("/api/workflows").json() == {"workflows": []}
