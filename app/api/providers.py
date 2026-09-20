from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sfvf.providers import (
    MODELS,
    PROVIDERS,
    Model,
    Provider,
    list_models,
    provider_configured,
)

router = APIRouter(prefix="/api")


def _configured_names(request: Request) -> set[str]:
    secrets = getattr(request.app.state, "secrets", None) or {}
    return set(secrets)  # secret NAMES only, never values


def _provider_capabilities(provider_id: str, provider: Provider) -> list[str]:
    caps: set[str] = set(provider.capabilities)
    for model in MODELS.values():
        if model.provider == provider_id:
            caps |= model.capabilities
    return sorted(caps)


class ProviderOut(BaseModel):
    id: str
    label: str
    configured: bool
    capabilities: list[str]


class ProvidersOut(BaseModel):
    providers: list[ProviderOut]


class OptionOut(BaseModel):
    id: str
    label: str
    configured: bool
    offered: bool


class OptionsOut(BaseModel):
    options: list[OptionOut]


@router.get("/providers", response_model=ProvidersOut)
def list_providers(request: Request) -> ProvidersOut:
    configured = _configured_names(request)
    return ProvidersOut(
        providers=[
            ProviderOut(
                id=pid,
                label=provider.label,
                configured=provider_configured(provider, configured),
                capabilities=_provider_capabilities(pid, provider),
            )
            for pid, provider in PROVIDERS.items()
        ]
    )


def _models_for_source(source: str) -> list[Model] | None:
    """Resolve an options_from source to a model list, or None if the source is unknown."""
    if source == "sfvf.models":
        return list_models()
    if source == "sfvf.models:image":
        return list_models("image")
    if source == "sfvf.models:video":
        return list_models("video")
    if source.endswith(".models"):
        provider_id = source[: -len(".models")]
        if provider_id in PROVIDERS:
            return [model for model in list_models() if model.provider == provider_id]
    return None


@router.get("/providers/options/{source}", response_model=OptionsOut)
def provider_options(source: str, request: Request) -> OptionsOut:
    models = _models_for_source(source)
    if models is None:
        raise HTTPException(status_code=404, detail=f"unknown option source {source!r}")
    configured = _configured_names(request)
    return OptionsOut(
        options=[
            OptionOut(
                id=model.id,
                label=model.label,
                configured=provider_configured(PROVIDERS[model.provider], configured),
                offered=True,
            )
            for model in models
        ]
    )
