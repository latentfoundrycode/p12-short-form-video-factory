"""TASK-SSN-A3 contract: app-side access to the owner library pool + read endpoints.

`create_app(..., library_dir=...)` injects the library root (default `app.paths.LIBRARY_DIR`); the
owner pool lives at `<library_dir>/_owner`. Two read endpoints back the Library tab:

- `GET /api/library/assets` -> `{"assets": [{id, kind, status, facets, description, grant}, ...]}`
  over the owner pool, ALL statuses (active + inactive), each merged with its access grant
  (`GrantStore`); an ungranted asset reports the default-deny grant `{"workflows": []}`.
- `GET /api/library/workflows` -> `{"workflows": [{id, label}, ...]}` from the registry snapshot,
  for the grant picker.

Assets are seeded BEFORE the app is built (like tests/api/test_learning_api.py). Supervisor-authored
frozen contract (RED-first); the builder implements app/main.py + app/api/library.py.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sfvf.grants import GrantStore
from sfvf.library import LibraryStore

from app.main import create_app
from tests.registry.fixtures import minimal_toml, write_plugin


def _seed_owner_asset(library_dir: Path, name: str, content: bytes, grant: dict) -> str:
    owner = library_dir / "_owner"
    store = LibraryStore(owner)
    src = library_dir / "src" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(content)
    asset = store.put(name, src, kind="music")
    GrantStore(owner).set_grant(asset.id, grant)
    return asset.id


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    write_plugin(workflows, "news-explainer", minimal_toml("news-explainer"))
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    app = create_app(workflows_dir=workflows, runs_dir=tmp_path / "runs", library_dir=library_dir)
    return TestClient(app), library_dir


def test_assets_endpoint_lists_owner_pool_with_grants(tmp_path: Path) -> None:
    client, library_dir = _client(tmp_path)
    asset_id = _seed_owner_asset(library_dir, "cosmic.mp3", b"AUDIO", {"all": True})
    resp = client.get("/api/library/assets")  # endpoint reads the pool live per request
    assert resp.status_code == 200
    assets = resp.json()["assets"]
    match = [a for a in assets if a["id"] == asset_id]
    assert len(match) == 1
    row = match[0]
    assert row["kind"] == "music"
    assert row["status"] == "active"
    assert row["grant"] == {"all": True}
    assert "facets" in row and "description" in row


def test_assets_endpoint_reports_default_deny_for_ungranted(tmp_path: Path) -> None:
    client, library_dir = _client(tmp_path)
    owner = library_dir / "_owner"
    store = LibraryStore(owner)
    src = library_dir / "src" / "nogrant.mp3"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"X")
    asset = store.put("nogrant.mp3", src, kind="sfx")  # no grant set
    row = next(a for a in client.get("/api/library/assets").json()["assets"] if a["id"] == asset.id)
    assert row["grant"] == {"workflows": []}


def test_assets_endpoint_includes_inactive(tmp_path: Path) -> None:
    client, library_dir = _client(tmp_path)
    asset_id = _seed_owner_asset(library_dir, "old.mp3", b"OLD", {"all": True})
    LibraryStore(library_dir / "_owner").deactivate(asset_id)
    row = next(a for a in client.get("/api/library/assets").json()["assets"] if a["id"] == asset_id)
    assert row["status"] == "inactive"  # the tab shows hidden assets too


def test_assets_endpoint_empty_when_no_owner_pool(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)  # nothing seeded; _owner may not exist yet
    resp = client.get("/api/library/assets")
    assert resp.status_code == 200
    assert resp.json()["assets"] == []


def test_workflows_endpoint_lists_registry(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    resp = client.get("/api/library/workflows")
    assert resp.status_code == 200
    workflows = resp.json()["workflows"]
    ids = [w["id"] for w in workflows]
    assert "news-explainer" in ids
    assert all("label" in w for w in workflows)


def test_assets_row_includes_display_name(tmp_path: Path) -> None:
    # The tab shows the friendly name the owner gave at upload (the asset's alias), so the row
    # must carry it. `_seed_owner_asset` puts with name == the filename.
    client, library_dir = _client(tmp_path)
    asset_id = _seed_owner_asset(library_dir, "cosmic.mp3", b"AUDIO", {"all": True})
    row = next(a for a in client.get("/api/library/assets").json()["assets"] if a["id"] == asset_id)
    assert row["name"] == "cosmic.mp3"
