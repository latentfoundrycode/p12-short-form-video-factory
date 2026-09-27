from __future__ import annotations

from contextlib import suppress
from typing import cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator
from sfvf.providers import PROVIDERS, provider_configured

from app.api.workflows import RegistryHolder, configured_secret_names
from app.core.secrets import SecretStore

router = APIRouter(prefix="/api")

_LOCKED_DETAIL = "secret store is locked; restart with SFVF_SECRETS_PASSPHRASE to edit keys"


class ProviderSettingsOut(BaseModel):
    id: str
    label: str
    secret_names: list[str]
    configured: bool


class SettingsOut(BaseModel):
    providers: list[ProviderSettingsOut]
    configured_secret_names: list[str]
    allowed_secret_names: list[str]


class SecretValueIn(BaseModel):
    value: str

    @field_validator("value")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value


def _holder(request: Request) -> RegistryHolder:
    return cast(RegistryHolder, request.app.state.registry)


def _allowed_secret_names(holder: RegistryHolder) -> set[str]:
    names: set[str] = set()
    for provider in PROVIDERS.values():
        names.update(provider.secret_names)
    for entry in holder.snapshot:
        if entry.manifest is not None:
            for key in entry.manifest.requires_keys:
                names.add(key.name)
    return names


def _refresh_secrets(request: Request, store: SecretStore) -> None:
    request.app.state.secrets = dict(store.all())
    registry = _holder(request)
    request.app.state.registry = RegistryHolder(
        registry.workflows_dir,
        configured=configured_secret_names(request.app.state.secrets),
        disabled_web_tiers=request.app.state.disabled_web_tiers,
        budget=request.app.state.budget,
    )


def _require_writable_store(request: Request) -> SecretStore:
    store = cast(SecretStore | None, getattr(request.app.state, "secret_store", None))
    if store is None:
        raise HTTPException(status_code=409, detail=_LOCKED_DETAIL)
    return store


@router.get("/settings", response_model=SettingsOut)
def get_settings(request: Request) -> SettingsOut:
    configured = configured_secret_names(request.app.state.secrets)
    allowed = _allowed_secret_names(_holder(request))
    return SettingsOut(
        providers=[
            ProviderSettingsOut(
                id=pid,
                label=provider.label,
                secret_names=list(provider.secret_names),
                configured=provider_configured(provider, configured),
            )
            for pid, provider in PROVIDERS.items()
        ],
        configured_secret_names=sorted(configured),
        allowed_secret_names=sorted(allowed),
    )


@router.put("/settings/secrets/{name}")
def put_secret(name: str, body: SecretValueIn, request: Request) -> dict[str, bool]:
    allowed = _allowed_secret_names(_holder(request))
    if name not in allowed:
        raise HTTPException(status_code=400, detail=f"unknown secret name {name!r}")
    store = _require_writable_store(request)
    store.set(name, body.value)
    _refresh_secrets(request, store)
    provider = next(
        (p for p in PROVIDERS.values() if name in p.secret_names),
        None,
    )
    configured = configured_secret_names(request.app.state.secrets)
    return {
        "ok": True,
        "configured": provider is not None and provider_configured(provider, configured),
    }


@router.delete("/settings/secrets/{name}")
def delete_secret(name: str, request: Request) -> dict[str, bool]:
    store = _require_writable_store(request)
    with suppress(KeyError):
        store.delete(name)
    _refresh_secrets(request, store)
    return {"ok": True}
