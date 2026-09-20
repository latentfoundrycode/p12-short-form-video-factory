"""Provider and model registry."""

from .registry import (
    MODELS,
    PROVIDERS,
    CapabilityError,
    Model,
    PriceHint,
    Provider,
    Ref,
    UnknownModelError,
    capabilities_offered,
    capable_models_without_adapter,
    list_models,
    provider_configured,
    providers_offering,
    resolve,
)

__all__ = [
    "MODELS",
    "PROVIDERS",
    "CapabilityError",
    "Model",
    "PriceHint",
    "Provider",
    "Ref",
    "UnknownModelError",
    "capabilities_offered",
    "capable_models_without_adapter",
    "list_models",
    "provider_configured",
    "providers_offering",
    "resolve",
]
