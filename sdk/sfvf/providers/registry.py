"""Provider and model registry mechanics."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
from importlib.util import find_spec


@dataclass(frozen=True)
class PriceHint:
    """A provider's last verified indicative model price."""

    unit: str
    basis: str
    amount: float
    verified: str


@dataclass(frozen=True)
class Provider:
    """Connection and metering metadata for an API provider."""

    id: str
    label: str
    secret_names: tuple[str, ...]
    meter: str
    meter_kind: str
    unit: str
    base_url: str
    adapter: str
    capabilities: frozenset[str] = frozenset()
    region: str = ""


@dataclass(frozen=True)
class Model:
    """A stable model identity and its provider-facing metadata."""

    id: str
    provider: str
    slug: str
    kind: str
    capabilities: frozenset[str]
    label: str
    price: PriceHint
    notes: str = ""
    region: str = ""


class UnknownModelError(LookupError):
    """Raised when a model id is absent from the registry."""


class CapabilityError(RuntimeError):
    """Raised when a model cannot provide a requested capability."""


_REF_KINDS = frozenset({"character", "style", "motion", "video"})


def Ref(kind: str, path: str) -> dict[str, str]:  # noqa: N802 - frozen public API
    """Return a cache-safe reference whose path string is its identity."""
    if kind not in _REF_KINDS:
        raise ValueError(f"unknown reference kind {kind!r}")
    return {"kind": kind, "path": path}


PROVIDERS: dict[str, Provider] = {
    "openrouter": Provider(
        "openrouter",
        "OpenRouter",
        ("OPENROUTER_API_KEY",),
        "openrouter",
        "fiat",
        "usd",
        "https://openrouter.ai/api/v1",
        "openrouter",
        capabilities=frozenset({"agents.structured", "agents.vision"}),
    ),
    "openai": Provider(
        "openai",
        "OpenAI",
        ("OPENAI_API_KEY",),
        "openai",
        "fiat",
        "usd",
        "https://api.openai.com",
        "openai",
    ),
    "google": Provider(
        "google",
        "Google (Agent Platform / Vertex)",
        ("GOOGLE_SA_JSON",),
        "google",
        "fiat",
        "usd",
        "https://aiplatform.googleapis.com",
        "google",
        region="us-central1",
    ),
    "bfl": Provider(
        "bfl",
        "Black Forest Labs",
        ("BFL_API_KEY",),
        "bfl",
        "credit",
        "credits",
        "https://api.bfl.ai",
        "bfl",
    ),
    "byteplus": Provider(
        "byteplus",
        "BytePlus ModelArk",
        ("BYTEPLUS_ARK_API_KEY",),
        "byteplus",
        "fiat",
        "usd",
        "https://ark.ap-southeast.bytepluses.com/api/v3",
        "byteplus",
    ),
    "minimax": Provider(
        "minimax",
        "MiniMax",
        ("MINIMAX_API_KEY",),
        "minimax",
        "fiat",
        "usd",
        "https://api.minimax.io",
        "minimax",
    ),
    "kling": Provider(
        "kling",
        "Kling",
        ("KLING_ACCESS_KEY", "KLING_SECRET_KEY"),
        "kling",
        "credit",
        "credits",
        "https://api-singapore.klingai.com",
        "kling",
    ),
    "openverse": Provider(
        "openverse",
        "Openverse",
        (),
        "openverse",
        "fiat",
        "usd",
        "https://api.openverse.org/v1",
        "openverse",
        capabilities=frozenset({"web.images.commons"}),
    ),
}

MODELS: dict[str, Model] = {
    "openai/gpt-image-2": Model(
        id="openai/gpt-image-2",
        provider="openai",
        slug="gpt-image-2",
        kind="image",
        capabilities=frozenset({"image.generate", "image.edit"}),
        label="OpenAI GPT Image 2",
        price=PriceHint(
            unit="usd",
            basis="per_image",
            amount=0.04,
            verified="2026-09-19",
        ),
        notes=(
            "priced per image; a single figure for now — size/quality-dependent pricing is a "
            "later refinement, and the real per-image cost is confirmed at the attended live smoke"
        ),
    ),
    "google/gemini-3.1-flash-image": Model(
        id="google/gemini-3.1-flash-image",
        provider="google",
        slug="gemini-3.1-flash-image",
        kind="image",
        capabilities=frozenset({"image.generate", "image.edit", "image.refs"}),
        label="Google Gemini 3.1 Flash Image (Nano Banana 2)",
        price=PriceHint(
            unit="usd",
            basis="per_image",
            amount=0.067,
            verified="2026-09-19",
        ),
        notes=(
            "Vertex :generateContent; ~$0.067/1MP output, flat-priced; the real price is "
            "confirmed at the live smoke; 2.5-flash-image is deprecated (retire 2027-03-15)"
        ),
        region="global",
    ),
    "google/veo-3.1-generate-001": Model(
        id="google/veo-3.1-generate-001",
        provider="google",
        slug="veo-3.1-generate-001",
        kind="video",
        capabilities=frozenset({"video.generate", "video.first_frame"}),
        label="Google Veo 3.1",
        price=PriceHint(
            unit="usd",
            basis="per_second",
            amount=0.40,
            verified="2026-09-19",
        ),
        notes=(
            "Vertex :predictLongRunning; priced per second of output (default 8s); no video.refs / "
            "last-frame (unconfirmed fields); the real $/s is confirmed at the live smoke"
        ),
    ),
    "bfl/flux-1.1-pro": Model(
        id="bfl/flux-1.1-pro",
        provider="bfl",
        slug="flux-pro-1.1",
        kind="image",
        capabilities=frozenset({"image.generate"}),
        label="BFL FLUX1.1 [pro]",
        price=PriceHint(unit="credits", basis="per_image", amount=4.0, verified="2026-09-19"),
        notes="priced ~4 credits/image (1 credit = $0.01); confirm at the attended live smoke",
    ),
    "bfl/flux-kontext-pro": Model(
        id="bfl/flux-kontext-pro",
        provider="bfl",
        slug="flux-kontext-pro",
        kind="image",
        capabilities=frozenset({"image.edit"}),
        label="BFL FLUX.1 Kontext [pro]",
        price=PriceHint(unit="credits", basis="per_image", amount=4.0, verified="2026-09-19"),
        notes=(
            "reference editing via input_image; priced ~4 credits/image; confirm at the live smoke"
        ),
    ),
    "byteplus/seedance-2.5": Model(
        id="byteplus/seedance-2.5",
        provider="byteplus",
        slug="dreamina-seedance-2-5-260628",
        kind="video",
        capabilities=frozenset({"video.generate", "video.refs", "video.first_frame"}),
        label="BytePlus Seedance 2.5",
        price=PriceHint(
            unit="usd",
            basis="per_1m_tokens",
            amount=10.70,
            verified="2026-09-19",
        ),
        notes=(
            "metered per 1M video tokens; the real rate is confirmed at the attended live smoke"
        ),
    ),
    "minimax/hailuo-h3": Model(
        id="minimax/hailuo-h3",
        provider="minimax",
        slug="MiniMax-H3",
        kind="video",
        capabilities=frozenset({"video.generate", "video.refs", "video.first_frame"}),
        label="MiniMax Hailuo H3",
        price=PriceHint(unit="usd", basis="per_second", amount=0.05, verified="2026-09-19"),
        notes=(
            "metered per output second (usage block); the real $/s is confirmed at the live smoke"
        ),
    ),
}


def resolve(
    model_id: str,
    *,
    providers: dict[str, Provider] = PROVIDERS,
    models: dict[str, Model] = MODELS,
) -> tuple[Provider, Model]:
    """Resolve a registered model id."""
    model = models.get(model_id)
    if model is not None:
        return providers[model.provider], model

    matches = get_close_matches(model_id, list(models), n=3)
    suggestion = f"; nearest: {', '.join(matches)}" if matches else ""
    raise UnknownModelError(f"unknown model {model_id!r}{suggestion}")


def list_models(
    kind: str | None = None,
    *,
    models: dict[str, Model] = MODELS,
) -> list[Model]:
    """List registered models, optionally restricted to one media kind."""
    if kind is None:
        return list(models.values())
    return [model for model in models.values() if model.kind == kind]


def provider_configured(provider: Provider, configured: set[str]) -> bool:
    """Return whether all secrets required by a provider are configured."""
    return all(name in configured for name in provider.secret_names)


def capabilities_offered(
    configured: set[str],
    *,
    providers: dict[str, Provider] = PROVIDERS,
    models: dict[str, Model] = MODELS,
) -> frozenset[str]:
    """Return capabilities offered by the configured providers and models."""
    capabilities: set[str] = set()
    configured_providers: set[str] = set()

    for provider_id, provider in providers.items():
        if provider_configured(provider, configured):
            configured_providers.add(provider_id)
            capabilities.update(provider.capabilities)

    for model in models.values():
        if model.provider in configured_providers:
            capabilities.update(model.capabilities)

    return frozenset(capabilities)


def providers_offering(
    capability: str,
    *,
    providers: dict[str, Provider] = PROVIDERS,
    models: dict[str, Model] = MODELS,
) -> list[str]:
    """Labels of providers that offer a capability (provider- or model-level), sorted, deduped."""
    labels: set[str] = set()
    for provider in providers.values():
        if capability in provider.capabilities:
            labels.add(provider.label)
    for model in models.values():
        if capability in model.capabilities:
            labels.add(providers[model.provider].label)
    return sorted(labels)


def capable_models_without_adapter(
    *,
    providers: dict[str, Provider] = PROVIDERS,
    models: dict[str, Model] = MODELS,
) -> list[str]:
    """List capable models whose provider adapter module cannot be imported."""
    offenders = [
        model.id
        for model in models.values()
        if model.capabilities
        and find_spec(f"sfvf.providers.{providers[model.provider].adapter}") is None
    ]
    return sorted(offenders)
