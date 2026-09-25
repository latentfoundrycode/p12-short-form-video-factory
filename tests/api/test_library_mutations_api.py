"""TASK-SSN-A6 contract: edit / grant / deactivate library assets via the API.

Backs the Library tab's detail-pane edits over the owner pool:
- `PUT /api/library/assets/{id}` (JSON `{facets?, caveats?}`) -> annotate; returns the updated row.
- `POST /api/library/assets/{id}/grant` (JSON grant `{"all": true}|{"workflows":[ids]}`) -> set the
  access grant; returns the updated row.
- `POST /api/library/assets/{id}/deactivate` and `.../reactivate` -> flip status; return the row.
Unknown id -> 404; malformed grant -> 400/422. Rows match the GET /assets shape.

Supervisor-authored frozen contract (RED-first); the builder implements app/api/library.py.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sfvf.grants import GrantStore
from sfvf.library import LibraryStore

from app.main import create_app
from tests.registry.fixtures import minimal_toml, write_plugin


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    write_plugin(workflows, "news-explainer", minimal_toml("news-explainer"))
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    app = create_app(workflows_dir=workflows, runs_dir=tmp_path / "runs", library_dir=library_dir)
    return TestClient(app), library_dir


def _seed(library_dir: Path, name: str, grant: dict) -> str:
    owner = library_dir / "_owner"
    src = library_dir / "src" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"AUDIO")
    asset = LibraryStore(owner).put(name, src, kind="music")
    GrantStore(owner).set_grant(asset.id, grant)
    return asset.id


def test_put_annotates_facets_and_caveats(tmp_path: Path) -> None:
    client, library_dir = _client(tmp_path)
    aid = _seed(library_dir, "a.mp3", {"all": True})
    resp = client.put(
        f"/api/library/assets/{aid}", json={"facets": {"mood": "calm"}, "caveats": "loops cleanly"}
    )
    assert resp.status_code == 200
    row = resp.json()
    assert row["facets"].get("mood") == "calm"
    assert row["id"] == aid


def test_post_grant_updates_access(tmp_path: Path) -> None:
    client, library_dir = _client(tmp_path)
    aid = _seed(library_dir, "b.mp3", {"all": True})
    resp = client.post(f"/api/library/assets/{aid}/grant", json={"workflows": ["news-explainer"]})
    assert resp.status_code == 200
    assert resp.json()["grant"] == {"workflows": ["news-explainer"]}
    assert GrantStore(library_dir / "_owner").get_grant(aid) == {"workflows": ["news-explainer"]}


def test_deactivate_and_reactivate(tmp_path: Path) -> None:
    client, library_dir = _client(tmp_path)
    aid = _seed(library_dir, "c.mp3", {"all": True})
    d = client.post(f"/api/library/assets/{aid}/deactivate")
    assert d.status_code == 200
    assert d.json()["status"] == "inactive"
    r = client.post(f"/api/library/assets/{aid}/reactivate")
    assert r.status_code == 200
    assert r.json()["status"] == "active"


def test_put_unknown_id_is_404(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    resp = client.put("/api/library/assets/" + "0" * 64, json={"caveats": "x"})
    assert resp.status_code == 404


def test_grant_unknown_id_is_404(tmp_path: Path) -> None:
    client, library_dir = _client(tmp_path)
    _seed(library_dir, "d.mp3", {"all": True})  # pool exists but this id is absent
    resp = client.post("/api/library/assets/" + "0" * 64 + "/grant", json={"all": True})
    assert resp.status_code == 404


def test_deactivate_unknown_id_is_404(tmp_path: Path) -> None:
    client, library_dir = _client(tmp_path)
    _seed(library_dir, "e.mp3", {"all": True})
    resp = client.post("/api/library/assets/" + "0" * 64 + "/deactivate")
    assert resp.status_code == 404


def test_grant_malformed_is_rejected(tmp_path: Path) -> None:
    client, library_dir = _client(tmp_path)
    aid = _seed(library_dir, "f.mp3", {"all": True})
    resp = client.post(f"/api/library/assets/{aid}/grant", json={"bogus": 1})
    assert resp.status_code in (400, 422)
