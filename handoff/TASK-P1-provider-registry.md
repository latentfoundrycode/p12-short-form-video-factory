# TASK — P-1: the model registry mechanics (provider layer)

## Goal (one sentence)
Create the `sfvf.providers` package holding the model registry mechanics — `Provider`/`Model`/`PriceHint`
shapes, the seven live `Provider` rows, `Ref`, `resolve()` + the routing rule (incl. the legacy-Higgsfield
allowlist mechanism), `provider_configured`, `capabilities_offered`, and the "a capable model must name an
adapter that exists" guard — so the frozen contract goes green. Pure data, no network, no adapters yet.

## Spec (docs/PROVIDER_LAYER_PLAN.md §3.2, §4 P-1) — authoritative
The provider layer chooses among many models from many API providers as an SFVF-core capability. This
increment lands ONLY the registry. Per the **seeding rule**: a model appears in `MODELS` only once its
adapter module exists, so `MODELS` is empty here and no model carries a capability yet. The real media
providers are registered as `Provider` rows with **no capabilities** (their capabilities arrive with their
models in later increments); OpenRouter is registered offering `agents.structured` only.

## Frozen contract (already committed — do NOT edit)
`tests/sdk/test_providers_registry.py`. Make it pass without changing it. The full suite must stay green.

## What to create — a new package `sdk/sfvf/providers/`

Suggested layout: `registry.py` for the data (dataclasses + `PROVIDERS`/`MODELS`), `__init__.py` re-exporting
the full public surface, and `openrouter.py` as a placeholder module (below). Keep the whole package free of
any `app.*` import and any third-party dependency (stdlib only: `dataclasses`, `importlib.util`, `difflib`).

### 1. Dataclasses (frozen)
```python
@dataclass(frozen=True)
class PriceHint:
    unit: str                 # e.g. "usd", "credits"
    basis: str                # one of: "per_image", "per_second", "per_1m_tokens"
    amount: float
    verified: str             # ISO date the price was checked, e.g. "2026-09-19"

@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    secret_names: tuple[str, ...]         # ALL must be configured for the provider to be usable
    meter: str                            # == id (one meter per provider)
    meter_kind: str                       # "fiat" | "credit"
    unit: str
    base_url: str                         # https://...
    adapter: str                          # name of the sfvf.providers.<adapter> module
    capabilities: frozenset[str] = frozenset()    # provider-level caps (OpenRouter: agents.structured)
    legacy_slugs: frozenset[str] = frozenset()    # only the deprecated higgsfield row uses this

@dataclass(frozen=True)
class Model:
    id: str                   # "provider/model", the stable id recorded in video.json
    provider: str
    slug: str                 # what the provider's API calls the model
    kind: str                 # "image" | "video"
    capabilities: frozenset[str]
    label: str
    price: PriceHint
    notes: str = ""
```

### 2. Errors
```python
class UnknownModelError(LookupError): ...
class CapabilityError(RuntimeError): ...   # raised at the call by media.* later; defined here for import
```

### 3. `Ref`
```python
_REF_KINDS = frozenset({"character", "style", "motion", "video"})
def Ref(kind: str, path: str) -> dict[str, str]:
    # a plain JSON-shaped value so it survives the step cache (SDK §5.5); the path string is IDENTITY,
    # not content (SDK §6.3) — do not read or hash the file here.
    if kind not in _REF_KINDS: raise ValueError(...); 
    return {"kind": kind, "path": path}
```

### 4. `PROVIDERS` — the seven live rows (exact)
```python
PROVIDERS: dict[str, Provider] = {
  "openrouter": Provider("openrouter", "OpenRouter", ("OPENROUTER_API_KEY",), "openrouter",
      "fiat", "usd", "https://openrouter.ai/api/v1", "openrouter",
      capabilities=frozenset({"agents.structured"})),
  "openai": Provider("openai", "OpenAI", ("OPENAI_API_KEY",), "openai",
      "fiat", "usd", "https://api.openai.com", "openai"),
  "google": Provider("google", "Google (Agent Platform / Vertex)", ("GOOGLE_SA_JSON",), "google",
      "fiat", "usd", "https://aiplatform.googleapis.com", "google"),
  "bfl": Provider("bfl", "Black Forest Labs", ("BFL_API_KEY",), "bfl",
      "credit", "credits", "https://api.bfl.ai", "bfl"),
  # meter_kind for byteplus/minimax/kling is PROVISIONAL — pinned from the live billing page in that
  # provider's own increment (P-4b / P-7 / P-10). The contract does not assert them.
  "byteplus": Provider("byteplus", "BytePlus ModelArk", ("BYTEPLUS_ARK_API_KEY",), "byteplus",
      "fiat", "usd", "https://ark.ap-southeast.bytepluses.com/api/v3", "byteplus"),
  "minimax": Provider("minimax", "MiniMax", ("MINIMAX_API_KEY",), "minimax",
      "credit", "credits", "https://api.minimax.io", "minimax"),
  "kling": Provider("kling", "Kling", ("KLING_ACCESS_KEY", "KLING_SECRET_KEY"), "kling",
      "credit", "credits", "https://api-singapore.klingai.com", "kling"),
}
MODELS: dict[str, Model] = {}   # empty at P-1 (seeding rule)
```
Do NOT add a `higgsfield` row — it is added in P-4a to carry the legacy path and removed in P-11.

### 5. `openrouter.py` — placeholder module
A module whose only P-1 job is to EXIST, so `capable_models_without_adapter` treats a model routed to the
`openrouter` adapter as having an adapter. Give it a module docstring saying the real adapter (delegating to
`sfvf.agents`) is wired in a later increment. No behaviour yet. (The `openai`/`google`/`bfl`/`byteplus`/
`minimax`/`kling` adapter modules are NOT created here — their providers have no models yet, so the guard
never looks for them.)

### 6. Functions (optional registry params default to the module globals, mirroring `meter_info(..., registry=)`)
```python
def resolve(model_id: str, *, providers=PROVIDERS, models=MODELS) -> tuple[Provider, Model]:
    # 1. exact id in models -> (providers[m.provider], m)
    # 2. else a legacy match: the first provider whose legacy_slugs contains model_id -> return that
    #    provider and a SYNTHESIZED Model(id=model_id, provider=<that>, slug=model_id, kind="video",
    #    capabilities=frozenset(), label=model_id, price=PriceHint("credits","per_second",0.0,"legacy"),
    #    notes="legacy"). (This is the only path that accepts an id whose prefix is not a provider.)
    # 3. else raise UnknownModelError(f"unknown model {model_id!r}"...) — include up to 3 nearest ids from
    #    difflib.get_close_matches(model_id, list(models)) in the message when any exist.

def list_models(kind: str | None = None, *, models=MODELS) -> list[Model]:
    # values, filtered by kind when given.

def provider_configured(provider: Provider, configured: set[str]) -> bool:
    # all(name in configured for name in provider.secret_names)

def capabilities_offered(configured: set[str], *, providers=PROVIDERS, models=MODELS) -> frozenset[str]:
    # union of: each CONFIGURED provider's .capabilities, plus each model whose provider is CONFIGURED
    # (all that provider's secret_names present) contributing model.capabilities.

def capable_models_without_adapter(*, providers=PROVIDERS, models=MODELS) -> list[str]:
    # sorted ids of models with a non-empty capability set whose provider's adapter module does NOT exist,
    # tested via importlib.util.find_spec(f"sfvf.providers.{providers[m.provider].adapter}") is None.
```

### 7. `__init__.py`
Re-export exactly: `PROVIDERS, MODELS, Provider, Model, PriceHint, Ref, UnknownModelError, CapabilityError,
resolve, list_models, provider_configured, capabilities_offered, capable_models_without_adapter`.

## Constraints / do-nots
- Create ONLY files under `sdk/sfvf/providers/`. Do NOT edit the frozen test, `sdk/sfvf/agents.py`,
  `sdk/sfvf/media/*`, `app/*`, or anything else.
- No `app.*` import (the SDK must not depend on the backend). No new third-party dependency (stdlib only).
- `resolve`/`capabilities_offered`/`list_models` must be PURE and read-only; `Ref` must not touch the filesystem.
- Keep `ruff check .`, `ruff format --check .`, `mypy` clean; ≤100 cols.

## Scope
- `sdk/sfvf/providers/__init__.py`
- `sdk/sfvf/providers/registry.py`
- `sdk/sfvf/providers/openrouter.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/sdk/test_providers_registry.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy` → clean.
