"""TASK-SSN-A5 contract: upload an asset to the owner library pool (multipart).

`POST /api/library/assets` accepts a multipart form: the audio `file`, a `name`, a `kind`
(music/sfx/voice), an access `grant` (JSON: `{"all": true}` or `{"workflows": [ids]}`), and
optional `mood`/`energy` facets. It validates the media type, enforces a max-byte cap DURING
streaming (an oversize upload is aborted, HTTP 413, and no asset is written), then stores the file
content-addressed in `<library_dir>/_owner` and records the grant. Returns the created asset row
(id/kind/status/facets/description/grant), matching the GET /assets shape.

Supervisor-authored frozen contract (RED-first); the builder implements app/api/library.py (+ the
`python-multipart` dependency is already admitted and pinned in requirements.txt).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sfvf.grants import GrantStore
from sfvf.library import LibraryStore

import app.api.library as library_mod
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


def _upload(client: TestClient, *, filename: str, content: bytes, content_type: str, data: dict):
    return client.post(
        "/api/library/assets",
        files={"file": (filename, io.BytesIO(content), content_type)},
        data=data,
    )


def test_upload_creates_asset_with_grant(tmp_path: Path) -> None:
    client, library_dir = _client(tmp_path)
    resp = _upload(
        client,
        filename="cosmic.mp3",
        content=b"ID3AUDIODATA",
        content_type="audio/mpeg",
        data={"name": "Cosmic Drift", "kind": "music", "grant": json.dumps({"all": True})},
    )
    assert resp.status_code in (200, 201)
    row = resp.json()
    assert row["kind"] == "music"
    assert row["status"] == "active"
    assert row["grant"] == {"all": True}
    owner = library_dir / "_owner"
    assert LibraryStore(owner).get(row["id"]) is not None  # stored in the owner pool
    assert GrantStore(owner).get_grant(row["id"]) == {"all": True}


def test_upload_stores_mood_energy_facets(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    resp = _upload(
        client,
        filename="tense.wav",
        content=b"RIFFWAVEDATA",
        content_type="audio/wav",
        data={
            "name": "Tension",
            "kind": "music",
            "grant": json.dumps({"workflows": ["news-explainer"]}),
            "mood": json.dumps(["ominous", "mysterious"]),  # Full model: multi-value arrays
            "energy": json.dumps(["building"]),
        },
    )
    assert resp.status_code in (200, 201)
    row = resp.json()
    assert sorted(row["mood"]) == ["mysterious", "ominous"]
    assert row["energy"] == ["building"]


def test_upload_rejects_non_audio_type(tmp_path: Path) -> None:
    client, library_dir = _client(tmp_path)
    resp = _upload(
        client,
        filename="evil.txt",
        content=b"not audio",
        content_type="text/plain",
        data={"name": "x", "kind": "music", "grant": json.dumps({"all": True})},
    )
    assert resp.status_code in (400, 415, 422)
    # nothing written
    owner = library_dir / "_owner"
    assert not owner.exists() or LibraryStore(owner).find(status=None) == []


def test_upload_rejects_oversize_during_streaming(tmp_path: Path, monkeypatch) -> None:
    client, library_dir = _client(tmp_path)
    monkeypatch.setattr(library_mod, "_MAX_UPLOAD_BYTES", 8, raising=False)
    resp = _upload(
        client,
        filename="big.mp3",
        content=b"WAY_TOO_MUCH_AUDIO_DATA",  # > 8 bytes
        content_type="audio/mpeg",
        data={"name": "big", "kind": "music", "grant": json.dumps({"all": True})},
    )
    assert resp.status_code == 413
    owner = library_dir / "_owner"
    assert not owner.exists() or LibraryStore(owner).find(status=None) == []


def test_upload_rejects_malformed_grant(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    resp = _upload(
        client,
        filename="a.mp3",
        content=b"AUDIO",
        content_type="audio/mpeg",
        data={"name": "a", "kind": "music", "grant": json.dumps({"bogus": 1})},
    )
    assert resp.status_code in (400, 422)
