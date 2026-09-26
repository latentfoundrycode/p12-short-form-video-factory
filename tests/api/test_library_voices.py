"""TASK-SSN-B4b contract: GET /api/library/voices lists the voice-picker's choices.

The launch form's voice picker is fed by one endpoint that returns the BUNDLED presets (from the
SDK's assets/voices/voices.json, ids `preset:<stem>`) plus the owner's own voice assets (library
assets of kind "voice", id = the asset id). Non-voice owner assets (music/sfx) are NOT listed. Each
row is `{id, label, source}` where source is "preset" or "asset".

Supervisor-authored frozen contract (RED-first); the builder implements app/api/library.py (+ a
public `bundled_voice_presets()` in sdk/sfvf/media/speech.py).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
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


def _seed(library_dir: Path, name: str, kind: str) -> str:
    owner = library_dir / "_owner"
    src = library_dir / "src" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"AUDIO-" + name.encode())
    return LibraryStore(owner).put(name, src, kind=kind).id


def test_voices_endpoint_lists_bundled_presets(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    resp = client.get("/api/library/voices")
    assert resp.status_code == 200
    voices = resp.json()["voices"]
    ids = {v["id"] for v in voices}
    # the 3 bundled public-domain presets are always available
    assert {"preset:warm-female", "preset:literary-female", "preset:classic-male"} <= ids
    for v in voices:
        assert v["label"] and "source" in v


def test_voices_endpoint_includes_owner_voice_assets_only(tmp_path: Path) -> None:
    client, library_dir = _client(tmp_path)
    voice_id = _seed(library_dir, "my-voice.wav", "voice")
    music_id = _seed(library_dir, "song.mp3", "music")
    voices = client.get("/api/library/voices").json()["voices"]
    ids = {v["id"] for v in voices}
    assert voice_id in ids  # the owner's voice asset is a pickable voice
    assert music_id not in ids  # a music asset is not a voice
    row = next(v for v in voices if v["id"] == voice_id)
    assert row["source"] == "asset"


def test_voices_endpoint_marks_preset_source(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    voices = client.get("/api/library/voices").json()["voices"]
    preset = next(v for v in voices if v["id"] == "preset:warm-female")
    assert preset["source"] == "preset"
