"""TASK-SSN-D3b contract: mix owner audio, and write a sanitized-sources description.

Two finishing pieces of the workflow's run():
- AUDIO: if the owner has granted an active MUSIC asset to this workflow, mix it under the narration
  (ducked) via `media.edit.mix`; otherwise degrade gracefully to narration-only.
- DESCRIPTION: `Result.description` lists the video's SOURCES — the researched article URLs plus the
  web-image source URLs — SANITIZED: only http/https URLs, de-duplicated, order preserved (a
  `javascript:`/`data:` URL that rode in on untrusted web-image metadata must be dropped). Security
  carry-forward from the D2 review.

Supervisor-authored (RED-first); the builder adds `_sanitize_source_urls`, `_video_description`, and
`_select_music` to main.py and wires them into run().
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_WF = Path(__file__).resolve().parents[2] / "workflows" / "sensational-science-news"


def _load_main():
    spec = importlib.util.spec_from_file_location("ssn_main_assemble_ut", _WF / "main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sanitize_source_urls_keeps_http_drops_others_and_dedupes() -> None:
    main = _load_main()
    urls = [
        "https://www.nature.com/a",
        "http://phys.org/b",
        "javascript:alert(1)",
        "data:text/html,evil",
        "https://www.nature.com/a",  # dup
        "ftp://example.com/x",
        "  https://www.science.org/c  ",  # trims
    ]
    out = main._sanitize_source_urls(urls)
    assert out == [
        "https://www.nature.com/a",
        "http://phys.org/b",
        "https://www.science.org/c",
    ], out


def test_video_description_lists_sanitized_sources() -> None:
    main = _load_main()
    article_urls = [
        "https://www.nature.com/a",
        "https://www.bbc.com/news/science_and_environment/x",
    ]
    image_urls = ["https://commons.wikimedia.org/img.jpg", "javascript:steal()"]
    desc = main._video_description(article_urls, image_urls)
    assert "https://www.nature.com/a" in desc
    assert "https://www.bbc.com/news/science_and_environment/x" in desc
    assert "https://commons.wikimedia.org/img.jpg" in desc
    assert "javascript:" not in desc  # injected image URL dropped
    # empty-safe
    assert isinstance(main._video_description([], []), str)


class _FakeAsset:
    def __init__(self, asset_id: str, kind: str) -> None:
        self.id = asset_id
        self.kind = kind


class _FakeLibrary:
    def __init__(self, assets: list[_FakeAsset], blob: Path | None) -> None:
        self._assets = assets
        self._blob = blob

    def find(self, *, tags=(), facets=None, status="active"):
        return list(self._assets)

    def path(self, name_or_id: str) -> Path | None:
        return self._blob


def test_select_music_none_when_no_music(tmp_path: Path, monkeypatch) -> None:
    main = _load_main()

    class _Ctx:
        library = _FakeLibrary([_FakeAsset("v1", "voice"), _FakeAsset("s1", "sfx")], None)
        paths = type("P", (), {"artifacts": tmp_path})()

    assert main._select_music(_Ctx()) is None


def test_select_music_picks_granted_music(tmp_path: Path) -> None:
    main = _load_main()
    blob = tmp_path / "song.mp3"
    blob.write_bytes(b"ID3fake-music-bytes")
    arts = tmp_path / "artifacts"
    arts.mkdir()

    class _Ctx:
        library = _FakeLibrary([_FakeAsset("m1", "music"), _FakeAsset("v1", "voice")], blob)
        paths = type("P", (), {"artifacts": arts})()

    rel = main._select_music(_Ctx())
    assert rel is not None
    assert rel.startswith("artifacts/")  # a video-relative path media.edit.mix can resolve
    assert (arts / Path(rel).name).is_file()  # the music blob was copied into artifacts
