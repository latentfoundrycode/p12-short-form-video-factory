"""Frozen contract - Settings tab F1a: the /api/settings secrets-management endpoints.

The Settings tab (PRD 8.7, replacing the placeholder) manages API keys through the GUI without
ever showing a stored value. This freezes the backend contract:

- ``GET /api/settings`` -> the providers (id, label, secret_names, configured), the
  ``configured_secret_names`` (names only), and ``allowed_secret_names`` (every built-in provider
  secret name UNION every installed workflow's ``requires_keys`` name). No secret VALUE anywhere.
- ``PUT /api/settings/secrets/{name}`` {"value": ...} -> stores the key in the encrypted store and
  refreshes app state so the provider becomes configured (and offered) WITHOUT a restart. Rejects a
  name that is neither a provider secret nor a workflow key, and rejects an empty/blank value.
- ``DELETE /api/settings/secrets/{name}`` -> removes the key (idempotent: a missing name succeeds).
- Writes require an unlocked store. When the app was built from an injected ``secrets=`` mapping
  (no live store / no passphrase), a write returns 409 with a message that contains no value.

Writes need a live ``SecretStore`` at request time, so these tests build the app with
``create_app(..., secret_store=store)``; the injected ``secrets=`` path is the locked case.
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.secrets import SecretsError, SecretStore
from app.main import create_app

_PASSPHRASE = "test-passphrase"
_SECRET_VALUE = "sk-do-not-leak-this-value-123456"


def _store(tmp: Path) -> SecretStore:
    return SecretStore(tmp / "secrets.bin", _PASSPHRASE)


def _writable_client(
    tmp: Path, store: SecretStore, workflows_dir: Path | None = None
) -> TestClient:
    return TestClient(create_app(workflows_dir or (tmp / "workflows"), secret_store=store))


def _locked_client(tmp: Path, secrets: dict[str, str]) -> TestClient:
    return TestClient(create_app(tmp / "workflows", secrets=secrets))


def _make_workflow(workflows_dir: Path, wid: str, key_name: str) -> None:
    """A minimal workflow that declares one custom required key (for the allowlist test)."""
    d = workflows_dir / wid
    d.mkdir(parents=True, exist_ok=True)
    (d / "workflow.toml").write_text(
        f'[workflow]\nid = "{wid}"\nname = "{wid}"\nversion = "1.0.0"\n'
        'entrypoint = "main:run"\nsdk = "1"\n'
        f'\n[[requires_keys]]\nname = "{key_name}"\nlabel = "Custom test key"\n',
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- GET


def test_get_settings_shape_and_configured_names(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set("OPENROUTER_API_KEY", _SECRET_VALUE)
    body = _writable_client(tmp_path, store).get("/api/settings").json()

    assert isinstance(body["providers"], list) and body["providers"]
    for p in body["providers"]:
        assert set(p) >= {"id", "label", "secret_names", "configured"}
        assert isinstance(p["configured"], bool)
    assert "OPENROUTER_API_KEY" in body["configured_secret_names"]
    assert "OPENROUTER_API_KEY" in body["allowed_secret_names"]
    # openrouter is configured now that its only secret is present
    by_id = {p["id"]: p for p in body["providers"]}
    assert by_id["openrouter"]["configured"] is True


def test_get_settings_never_returns_a_secret_value(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set("OPENROUTER_API_KEY", _SECRET_VALUE)
    resp = _writable_client(tmp_path, store).get("/api/settings")
    assert _SECRET_VALUE not in resp.text


def test_allowed_names_include_provider_secrets_and_workflow_keys(tmp_path: Path) -> None:
    wf_dir = tmp_path / "workflows"
    _make_workflow(wf_dir, "custom-wf", "CUSTOM_TEST_KEY")
    store = _store(tmp_path)
    body = _writable_client(tmp_path, store, workflows_dir=wf_dir).get("/api/settings").json()
    allowed = set(body["allowed_secret_names"])
    assert "OPENROUTER_API_KEY" in allowed  # built-in provider secret
    assert "CUSTOM_TEST_KEY" in allowed  # workflow requires_keys name


# --------------------------------------------------------------------------- PUT


def test_put_secret_makes_provider_configured_without_restart(tmp_path: Path) -> None:
    store = _store(tmp_path)
    client = _writable_client(tmp_path, store)

    assert {p["id"]: p for p in client.get("/api/settings").json()["providers"]}["openrouter"][
        "configured"
    ] is False

    resp = client.put("/api/settings/secrets/OPENROUTER_API_KEY", json={"value": _SECRET_VALUE})
    assert resp.status_code == 200

    # persisted to the encrypted store
    assert store.get("OPENROUTER_API_KEY") == _SECRET_VALUE
    # reflected immediately in this same app instance (state + registry refreshed)
    assert {p["id"]: p for p in client.get("/api/settings").json()["providers"]}["openrouter"][
        "configured"
    ] is True
    assert {p["id"]: p for p in client.get("/api/providers").json()["providers"]}["openrouter"][
        "configured"
    ] is True


def test_put_workflow_key_is_allowed(tmp_path: Path) -> None:
    wf_dir = tmp_path / "workflows"
    _make_workflow(wf_dir, "custom-wf", "CUSTOM_TEST_KEY")
    store = _store(tmp_path)
    client = _writable_client(tmp_path, store, workflows_dir=wf_dir)
    resp = client.put("/api/settings/secrets/CUSTOM_TEST_KEY", json={"value": "a-value"})
    assert resp.status_code == 200
    assert store.get("CUSTOM_TEST_KEY") == "a-value"


def test_put_unknown_name_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    resp = _writable_client(tmp_path, store).put(
        "/api/settings/secrets/NOT_A_REAL_KEY", json={"value": "x"}
    )
    assert resp.status_code in (400, 422)
    assert "NOT_A_REAL_KEY" not in store.names()


def test_put_blank_value_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    client = _writable_client(tmp_path, store)
    for blank in ("", "   "):
        resp = client.put("/api/settings/secrets/OPENROUTER_API_KEY", json={"value": blank})
        assert resp.status_code in (400, 422)
    assert "OPENROUTER_API_KEY" not in store.names()


def test_put_on_locked_store_returns_409_without_value(tmp_path: Path) -> None:
    client = _locked_client(tmp_path, secrets={})
    resp = client.put("/api/settings/secrets/OPENROUTER_API_KEY", json={"value": _SECRET_VALUE})
    assert resp.status_code == 409
    assert _SECRET_VALUE not in resp.text


# --------------------------------------------------------------------------- DELETE


def test_delete_removes_and_deconfigures(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set("OPENROUTER_API_KEY", _SECRET_VALUE)
    client = _writable_client(tmp_path, store)
    resp = client.delete("/api/settings/secrets/OPENROUTER_API_KEY")
    assert resp.status_code == 200
    assert "OPENROUTER_API_KEY" not in store.names()
    assert {p["id"]: p for p in client.get("/api/settings").json()["providers"]}["openrouter"][
        "configured"
    ] is False


def test_delete_missing_name_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    resp = _writable_client(tmp_path, store).delete("/api/settings/secrets/OPENROUTER_API_KEY")
    assert resp.status_code == 200


def test_delete_on_locked_store_returns_409(tmp_path: Path) -> None:
    resp = _locked_client(tmp_path, secrets={}).delete("/api/settings/secrets/OPENROUTER_API_KEY")
    assert resp.status_code == 409


# ------------------------------------- freshness for long-lived captures + value hygiene


def test_put_preserves_state_secrets_identity(tmp_path: Path) -> None:
    # The scheduler lifespan captures app.state.secrets BY REFERENCE at startup; a settings write
    # must keep that same dict object current (mutate in place) so scheduled/unattended runs see a
    # newly stored key without a restart, rather than rebinding to a new object the scheduler
    # never sees.
    store = _store(tmp_path)
    client = _writable_client(tmp_path, store)
    before = client.app.state.secrets
    client.put("/api/settings/secrets/OPENROUTER_API_KEY", json={"value": _SECRET_VALUE})
    assert client.app.state.secrets is before
    assert client.app.state.secrets.get("OPENROUTER_API_KEY") == _SECRET_VALUE


def test_delete_preserves_state_secrets_identity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set("OPENROUTER_API_KEY", _SECRET_VALUE)
    client = _writable_client(tmp_path, store)
    before = client.app.state.secrets
    client.delete("/api/settings/secrets/OPENROUTER_API_KEY")
    assert client.app.state.secrets is before
    assert "OPENROUTER_API_KEY" not in client.app.state.secrets


def test_put_strips_surrounding_whitespace(tmp_path: Path) -> None:
    store = _store(tmp_path)
    client = _writable_client(tmp_path, store)
    resp = client.put(
        "/api/settings/secrets/OPENROUTER_API_KEY", json={"value": f"  {_SECRET_VALUE}  "}
    )
    assert resp.status_code == 200
    assert store.get("OPENROUTER_API_KEY") == _SECRET_VALUE


def test_refresh_failure_leaves_previous_secrets_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The scheduler holds app.state.secrets by reference; the post-write refresh must decrypt the
    # store BEFORE mutating the live map, so a failed reload never leaves it empty (which would
    # make a scheduled tick inject no secrets). Load-before-clear.
    store = _store(tmp_path)
    store.set("OPENROUTER_API_KEY", _SECRET_VALUE)
    client = _writable_client(tmp_path, store)
    assert "OPENROUTER_API_KEY" in client.app.state.secrets

    def boom() -> dict[str, str]:
        raise SecretsError("decrypt failed")

    monkeypatch.setattr(store, "all", boom)
    with suppress(Exception):
        client.put("/api/settings/secrets/GOOGLE_SA_JSON", json={"value": "x"})
    # the previously loaded map must still be intact, not wiped
    assert client.app.state.secrets.get("OPENROUTER_API_KEY") == _SECRET_VALUE


# ------------------------------------- global defaults (F1b)

_DEFAULTS_ENV = (
    "SFVF_SILENCE_LIMIT_SECONDS",
    "SFVF_DEFAULT_CONCURRENCY",
    "SFVF_DEFAULT_STEP_CONCURRENCY",
    "SFVF_CACHE_MAX_BYTES",
)


def _isolate_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.paths.DATA_ROOT", tmp_path)
    for var in _DEFAULTS_ENV:
        monkeypatch.delenv(var, raising=False)


def test_get_settings_includes_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_defaults(tmp_path, monkeypatch)
    store = _store(tmp_path)
    body = _writable_client(tmp_path, store).get("/api/settings").json()
    assert "defaults" in body
    fields = {
        "silence_limit_seconds",
        "default_concurrency",
        "default_step_concurrency",
        "cache_max_bytes",
    }
    assert fields <= set(body["defaults"])
    for field in fields:
        cell = body["defaults"][field]
        assert {"effective", "source"} <= set(cell)
        assert cell["source"] in {"env", "stored", "default"}


def test_put_defaults_persists_and_reflects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_defaults(tmp_path, monkeypatch)
    store = _store(tmp_path)
    client = _writable_client(tmp_path, store)
    resp = client.put(
        "/api/settings/defaults", json={"silence_limit_seconds": 90, "default_concurrency": 2}
    )
    assert resp.status_code == 200
    defaults = client.get("/api/settings").json()["defaults"]
    assert defaults["silence_limit_seconds"]["effective"] == 90
    assert defaults["silence_limit_seconds"]["source"] == "stored"
    assert defaults["default_concurrency"]["effective"] == 2


def test_put_defaults_rejects_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_defaults(tmp_path, monkeypatch)
    store = _store(tmp_path)
    client = _writable_client(tmp_path, store)
    resp = client.put("/api/settings/defaults", json={"default_concurrency": 0})
    assert resp.status_code in (400, 422)


def test_put_defaults_rejects_bool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # JSON true must not be coerced to 1 and stored (pydantic lax mode would otherwise accept it).
    _isolate_defaults(tmp_path, monkeypatch)
    client = _writable_client(tmp_path, _store(tmp_path))
    for field in (
        "silence_limit_seconds",
        "default_concurrency",
        "default_step_concurrency",
        "cache_max_bytes",
    ):
        resp = client.put("/api/settings/defaults", json={field: True})
        assert resp.status_code in (400, 422), (
            f"{field}=true must be rejected, got {resp.status_code}"
        )
    # nothing was stored: fields still report the built-in default
    defaults = client.get("/api/settings").json()["defaults"]
    assert defaults["cache_max_bytes"]["source"] == "default"
    assert defaults["silence_limit_seconds"]["source"] == "default"
