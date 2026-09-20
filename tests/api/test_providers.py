"""Frozen contract — Stage P, P-8c: the /api/providers endpoints.

Two read-only GET endpoints let the Run pop-up show models across providers and mark what is
configured:

- `GET /api/providers` — every registered provider with its display label, whether it is CONFIGURED
  (all its secret names present in this app's secrets), and the capabilities it would offer
  (provider-level plus its models', config-independent).
- `GET /api/providers/options/{source}` — a registry-backed option list for a manifest param's
  `options_from`. Sources: `sfvf.models` (all), `sfvf.models:image`, `sfvf.models:video`, and
  `<provider>.models`. Each option is {id, label, configured, offered}. An unknown source is 404.

Configuration is driven by `create_app(secrets=...)` -> `app.state.secrets`; the endpoints read only
the secret NAMES (keys), never values.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sfvf.providers import PROVIDERS

from app.main import create_app


def _client(tmp: Path, secrets: dict[str, str] | None = None) -> TestClient:
    return TestClient(create_app(tmp, secrets=secrets or {}))


# ---------------------------------------------------------------------------
# GET /api/providers
# ---------------------------------------------------------------------------


def test_providers_lists_every_registry_provider(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/api/providers").json()
    assert body["providers"]  # non-empty
    ids = {p["id"] for p in body["providers"]}
    assert ids == set(PROVIDERS)
    for p in body["providers"]:
        assert set(p) == {"id", "label", "configured", "capabilities"}
        assert isinstance(p["configured"], bool)
        assert isinstance(p["capabilities"], list)


def test_provider_capabilities_are_config_independent(tmp_path: Path) -> None:
    # openrouter offers agents.structured + agents.vision (provider-level); openai offers
    # image.generate (model).
    body = _client(tmp_path).get("/api/providers").json()
    by_id = {p["id"]: p for p in body["providers"]}
    assert "agents.structured" in by_id["openrouter"]["capabilities"]
    assert "agents.vision" in by_id["openrouter"]["capabilities"]
    assert "image.generate" in by_id["openai"]["capabilities"]
    assert "video.generate" in by_id["minimax"]["capabilities"]


def test_provider_configured_reflects_secret_names(tmp_path: Path) -> None:
    body = _client(tmp_path, secrets={"OPENAI_API_KEY": "x"}).get("/api/providers").json()
    by_id = {p["id"]: p for p in body["providers"]}
    assert by_id["openai"]["configured"] is True
    assert by_id["openrouter"]["configured"] is False


# ---------------------------------------------------------------------------
# GET /api/providers/options/{source}
# ---------------------------------------------------------------------------


def _options(client: TestClient, source: str) -> list[dict]:
    response = client.get(f"/api/providers/options/{source}")
    assert response.status_code == 200
    return response.json()["options"]


def test_options_sfvf_models_lists_all_models(tmp_path: Path) -> None:
    options = _options(_client(tmp_path), "sfvf.models")
    ids = {o["id"] for o in options}
    assert "openai/gpt-image-2" in ids
    assert "byteplus/seedance-2.5" in ids
    for o in options:
        assert set(o) == {"id", "label", "configured", "offered"}
        assert o["offered"] is True


def test_options_partition_by_kind(tmp_path: Path) -> None:
    client = _client(tmp_path)
    image_ids = {o["id"] for o in _options(client, "sfvf.models:image")}
    video_ids = {o["id"] for o in _options(client, "sfvf.models:video")}
    assert "openai/gpt-image-2" in image_ids and "openai/gpt-image-2" not in video_ids
    assert "byteplus/seedance-2.5" in video_ids and "byteplus/seedance-2.5" not in image_ids
    assert image_ids.isdisjoint(video_ids)


def test_options_by_provider(tmp_path: Path) -> None:
    ids = {o["id"] for o in _options(_client(tmp_path), "openai.models")}
    assert "openai/gpt-image-2" in ids
    assert all(o_id.startswith("openai/") for o_id in ids)


def test_options_configured_reflects_provider_config(tmp_path: Path) -> None:
    client = _client(tmp_path, secrets={"OPENAI_API_KEY": "x"})
    by_id = {o["id"]: o for o in _options(client, "sfvf.models")}
    assert by_id["openai/gpt-image-2"]["configured"] is True
    # a model whose provider key is not present is not configured
    assert by_id["byteplus/seedance-2.5"]["configured"] is False


def test_unknown_source_is_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/api/providers/options/bogus").status_code == 404
    assert client.get("/api/providers/options/nonesuch.models").status_code == 404
    assert client.get("/api/providers/options/sfvf.models:audio").status_code == 404
