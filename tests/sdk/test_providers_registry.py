"""Frozen contract — Stage P, P-1: the model registry mechanics (pure data, no network).

The provider layer (Architecture §5.5 amendment 2026-09-19; docs/PROVIDER_LAYER_PLAN.md) chooses among
many models from many API providers as a capability of SFVF core. P-1 lands ONLY the registry mechanics:
the `Provider`/`Model`/`PriceHint` shapes, the seven live `Provider` rows, `Ref`, resolution + the routing
rule (incl. the legacy-Higgsfield allowlist mechanism), `provider_configured`, `capabilities_offered`, and
the "a capable model must name an adapter that exists" invariant. Adapters and model rows arrive in later
increments; per the SEEDING RULE, no model carries a capability until its adapter exists — so `MODELS` is
empty here and the capability invariant is exercised against controlled in-test registries.

Registry functions take optional `providers=`/`models=`/`configured=` arguments (mirroring
`app.core.meters.meter_info(..., registry=…)`), so behaviour is pinned against a controlled fake registry
without depending on which real models happen to be seeded yet. No network, no secrets, no app import.
"""

from __future__ import annotations

import json

import pytest

from sfvf.cache import _canonicalize, _canonical_json
from sfvf.providers import (
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
    resolve,
)

# ---------------------------------------------------------------------------
# A controlled fake registry: two media providers (one configured in tests, one not) plus a
# provider-level capability provider and a deprecated legacy provider. Nothing here touches the
# real rows, so these assertions stay stable as real providers/models are added in later increments.
# ---------------------------------------------------------------------------

_PRICE = PriceHint(unit="usd", basis="per_image", amount=0.04, verified="2026-09-19")


def _fake_providers() -> dict[str, Provider]:
    return {
        "acme": Provider(
            id="acme", label="Acme", secret_names=("ACME_API_KEY",), meter="acme",
            meter_kind="fiat", unit="usd", base_url="https://api.acme.test",
            adapter="openrouter",  # a module that EXISTS in sfvf.providers, so the capable-model check passes
        ),
        "beta": Provider(
            id="beta", label="Beta", secret_names=("BETA_ID", "BETA_SECRET"), meter="beta",
            meter_kind="credit", unit="credits", base_url="https://api.beta.test",
            adapter="openrouter",
        ),
        "words": Provider(
            id="words", label="Words", secret_names=("WORDS_API_KEY",), meter="words",
            meter_kind="fiat", unit="usd", base_url="https://api.words.test",
            adapter="openrouter", capabilities=frozenset({"agents.structured"}),
        ),
        "higgsfield": Provider(
            id="higgsfield", label="Higgsfield (deprecated)", secret_names=("HIGGSFIELD_API_KEY",),
            meter="higgsfield", meter_kind="credit", unit="credits",
            base_url="https://api.higgsfield.ai", adapter="higgsfield",
            legacy_slugs=frozenset({"sora-2/text-to-video", "kling-video/v2.5-turbo/pro/text-to-video"}),
        ),
    }


def _fake_models() -> dict[str, Model]:
    return {
        "acme/photo": Model(
            id="acme/photo", provider="acme", slug="photo-1", kind="image",
            capabilities=frozenset({"image.generate", "image.edit"}), label="Acme Photo", price=_PRICE,
        ),
        "beta/clip": Model(
            id="beta/clip", provider="beta", slug="clip-1", kind="video",
            capabilities=frozenset({"video.generate", "video.refs"}), label="Beta Clip", price=_PRICE,
        ),
    }


# ---------------------------------------------------------------------------
# The real Provider rows (P-1 lands the seven live providers; no models yet).
# ---------------------------------------------------------------------------

_EXPECTED_PROVIDER_IDS = frozenset(
    {"openrouter", "openai", "google", "bfl", "byteplus", "minimax", "kling"}
)


def test_exactly_the_seven_live_providers_are_registered() -> None:
    # The deprecated `higgsfield` row is added in P-4a (to carry the legacy path) and deleted in P-11;
    # it must NOT be present at P-1.
    assert set(PROVIDERS) == _EXPECTED_PROVIDER_IDS
    for pid, provider in PROVIDERS.items():
        assert provider.id == pid


def test_every_provider_row_is_well_formed() -> None:
    for provider in PROVIDERS.values():
        assert isinstance(provider.secret_names, tuple) and provider.secret_names
        assert all(isinstance(n, str) and n for n in provider.secret_names)
        assert provider.base_url.startswith("https://")
        assert isinstance(provider.meter, str) and provider.meter
        assert provider.meter_kind in {"fiat", "credit"}
        assert isinstance(provider.unit, str) and provider.unit
        assert isinstance(provider.adapter, str) and provider.adapter
        assert isinstance(provider.capabilities, frozenset)


def test_openrouter_offers_structured_output_only_not_vision() -> None:
    # OpenRouter is registered so `agents.structured` is honestly accounted for; `agents.vision` is
    # deliberately NOT offered because `agents.llm` still raises on image attachments (plan §2, §3.7).
    openrouter = PROVIDERS["openrouter"]
    assert openrouter.capabilities == frozenset({"agents.structured"})
    assert "agents.vision" not in openrouter.capabilities


def test_media_providers_declare_no_provider_level_capabilities() -> None:
    # Media capabilities come from MODELS, added per adapter; the provider rows carry none at P-1.
    for pid in _EXPECTED_PROVIDER_IDS - {"openrouter"}:
        assert PROVIDERS[pid].capabilities == frozenset()


def test_the_decided_meter_kinds_and_secret_names_are_pinned() -> None:
    # These were decided at sign-off; BytePlus/MiniMax/Kling meter kinds are pinned in their own
    # adapter increments, so they are intentionally NOT asserted here.
    assert PROVIDERS["openai"].meter_kind == "fiat" and PROVIDERS["openai"].unit == "usd"
    assert PROVIDERS["google"].meter_kind == "fiat" and PROVIDERS["google"].unit == "usd"
    assert PROVIDERS["bfl"].meter_kind == "credit"
    # Google is the Agent Platform / Vertex service-account path: one credential secret.
    assert PROVIDERS["google"].secret_names == ("GOOGLE_SA_JSON",)
    # Kling authenticates with an access-key/secret-key pair; BOTH are required to be configured.
    assert PROVIDERS["kling"].secret_names == ("KLING_ACCESS_KEY", "KLING_SECRET_KEY")


def test_no_models_are_seeded_yet_and_none_carry_capabilities() -> None:
    # SEEDING RULE (§3.2): a model appears only once its adapter exists. P-1 has no adapters.
    assert MODELS == {}
    assert list_models() == []


def test_each_real_provider_meter_equals_its_id() -> None:
    # One meter per provider, meter id == provider id (drives the per-provider budget cap + Statistics).
    for pid, provider in PROVIDERS.items():
        assert provider.meter == pid


# ---------------------------------------------------------------------------
# Resolution + the routing rule.
# ---------------------------------------------------------------------------

def test_resolve_returns_provider_and_model() -> None:
    providers, models = _fake_providers(), _fake_models()
    provider, model = resolve("acme/photo", providers=providers, models=models)
    assert provider.id == "acme"
    assert model.id == "acme/photo" and model.slug == "photo-1" and model.kind == "image"


def test_resolve_unknown_model_under_a_known_provider_suggests_nearest() -> None:
    providers, models = _fake_providers(), _fake_models()
    with pytest.raises(UnknownModelError) as exc:
        resolve("acme/photoo", providers=providers, models=models)
    message = str(exc.value)
    assert "acme/photoo" in message
    assert "acme/photo" in message  # names the nearest real id rather than failing blankly


def test_resolve_rejects_an_unregistered_provider_prefix() -> None:
    # Routing rule: an id resolves only if the segment before the first '/' is a registered provider.
    # A typo in a new-style id must be an UnknownModelError, never a paid submit to the wrong provider.
    providers, models = _fake_providers(), _fake_models()
    with pytest.raises(UnknownModelError):
        resolve("acmee/photo", providers=providers, models=models)


def test_unknown_model_error_is_a_lookup_error() -> None:
    assert issubclass(UnknownModelError, LookupError)


def test_legacy_higgsfield_slug_resolves_only_from_the_allowlist() -> None:
    # The legacy path (Architecture pre-2026-09-19) uses bare slugs that themselves contain '/', e.g.
    # `sora-2/text-to-video`, whose prefix is NOT a provider. Such an id resolves to the deprecated
    # `higgsfield` provider ONLY when it is in that provider's `legacy_slugs`. Mechanism lives here;
    # the real higgsfield row + allowlist are added in P-4a and deleted in P-11.
    providers, models = _fake_providers(), _fake_models()
    provider, model = resolve("sora-2/text-to-video", providers=providers, models=models)
    assert provider.id == "higgsfield"
    assert model.slug == "sora-2/text-to-video" and model.kind == "video"

    with pytest.raises(UnknownModelError):
        resolve("sora-2/not-on-the-allowlist", providers=providers, models=models)


def test_without_a_higgsfield_row_legacy_slugs_do_not_resolve() -> None:
    # Once P-11 removes the deprecated row, the same bare slug is simply unknown.
    providers = {k: v for k, v in _fake_providers().items() if k != "higgsfield"}
    with pytest.raises(UnknownModelError):
        resolve("sora-2/text-to-video", providers=providers, models=_fake_models())


# ---------------------------------------------------------------------------
# Configuration + capability offering.
# ---------------------------------------------------------------------------

def test_provider_configured_requires_every_secret_name() -> None:
    providers = _fake_providers()
    assert provider_configured(providers["acme"], {"ACME_API_KEY"}) is True
    assert provider_configured(providers["acme"], set()) is False
    # Beta needs BOTH names (mirrors Kling's access-key/secret-key pair).
    assert provider_configured(providers["beta"], {"BETA_ID"}) is False
    assert provider_configured(providers["beta"], {"BETA_ID", "BETA_SECRET"}) is True


def test_capabilities_offered_unions_configured_providers_and_their_models() -> None:
    providers, models = _fake_providers(), _fake_models()
    # Only acme configured: its models' capabilities, nothing else.
    assert capabilities_offered({"ACME_API_KEY"}, providers=providers, models=models) == frozenset(
        {"image.generate", "image.edit"}
    )
    # acme + words: media caps from acme's model + words' provider-level agents.structured.
    assert capabilities_offered(
        {"ACME_API_KEY", "WORDS_API_KEY"}, providers=providers, models=models
    ) == frozenset({"image.generate", "image.edit", "agents.structured"})
    # Nothing configured: nothing offered (this is what blocks a workflow at scan time, PRD §8.2).
    assert capabilities_offered(set(), providers=providers, models=models) == frozenset()


def test_capabilities_offered_ignores_a_partially_configured_provider() -> None:
    providers, models = _fake_providers(), _fake_models()
    # Beta needs both secrets; with one, its video capabilities are NOT offered.
    assert capabilities_offered({"BETA_ID"}, providers=providers, models=models) == frozenset()
    assert capabilities_offered(
        {"BETA_ID", "BETA_SECRET"}, providers=providers, models=models
    ) == frozenset({"video.generate", "video.refs"})


def test_real_registry_offers_structured_output_when_openrouter_configured() -> None:
    # Against the REAL rows: media providers have no models yet, so only OpenRouter contributes.
    assert capabilities_offered({"OPENROUTER_API_KEY"}) == frozenset({"agents.structured"})
    assert capabilities_offered(set()) == frozenset()


# ---------------------------------------------------------------------------
# The "a capable model must name an adapter that exists" invariant.
# ---------------------------------------------------------------------------

def test_capable_models_without_adapter_flags_a_missing_adapter() -> None:
    providers = _fake_providers()
    # A model with a capability whose provider names a non-existent adapter module is an offender.
    providers["ghosted"] = Provider(
        id="ghosted", label="Ghost", secret_names=("G",), meter="ghosted", meter_kind="fiat",
        unit="usd", base_url="https://api.ghost.test", adapter="does_not_exist",
    )
    models = _fake_models()
    models["ghosted/x"] = Model(
        id="ghosted/x", provider="ghosted", slug="x", kind="image",
        capabilities=frozenset({"image.generate"}), label="X", price=_PRICE,
    )
    offenders = capable_models_without_adapter(providers=providers, models=models)
    assert "ghosted/x" in offenders
    assert "acme/photo" not in offenders  # names the existing `openrouter` adapter module


def test_the_real_registry_has_no_capable_model_without_an_adapter() -> None:
    # Vacuously true at P-1 (MODELS is empty); the guard that keeps it true as adapters land.
    assert capable_models_without_adapter() == []


# ---------------------------------------------------------------------------
# Ref — the reference/frame value handed to media.image / media.video.
# ---------------------------------------------------------------------------

def test_ref_is_a_plain_json_value_that_round_trips_the_step_cache() -> None:
    ref = Ref("character", "artifacts/sheet.png")
    assert ref == {"kind": "character", "path": "artifacts/sheet.png"}
    # It must survive the JSON step cache unchanged (SDK §5.5): produce == restore.
    assert json.loads(_canonical_json(ref)) == ref


def test_ref_accepts_the_four_kinds_and_rejects_others() -> None:
    for kind in ("character", "style", "motion", "video"):
        assert Ref(kind, "a.png")["kind"] == kind
    with pytest.raises(ValueError):
        Ref("mascot", "a.png")


def test_ref_path_is_identity_not_content() -> None:
    # A Ref's path is a STRING, so the step cache hashes it as text — the referenced file is NOT
    # content-digested (that is why a step re-running when the sheet changes must put the Path in
    # `inputs`; SDK §6.3). Canonicalising a Ref leaves the path string verbatim.
    ref = Ref("character", "artifacts/sheet.png")
    assert isinstance(ref["path"], str)
    assert _canonicalize(ref) == {"kind": "character", "path": "artifacts/sheet.png"}


def test_capability_error_is_defined_for_the_call_sites() -> None:
    # Raised at the call by media.image/media.video for an unsupported ref/kind combination (§6.3);
    # a RuntimeError so existing `pytest.raises(RuntimeError)` adapter contracts hold.
    assert issubclass(CapabilityError, RuntimeError)
