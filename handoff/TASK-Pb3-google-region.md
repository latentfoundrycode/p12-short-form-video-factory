# TASK-Pb3 — Google: per-model region (Gemini image is global-only)

The P-B live smoke proved `gemini-3.1-flash-image` is served only on `locations/global` (a call to `us-central1` 404s "Publisher model ... not found"), while Veo `veo-3.1-generate-001` is `us-central1`-only. The registry pins one `region` on the shared `google` Provider row, which cannot express both. A frozen RED contract already fails: `tests/integration/test_google_image.py` (it now expects the image call at the global endpoint). Make it pass without regressing Veo, by adding a per-model region override.

## The fix — two files

### 1. `sdk/sfvf/providers/registry.py`
- Add an optional field to the `Model` dataclass (the class with `id/provider/slug/kind/capabilities/label/price/notes`): `region: str = ""` (after `notes: str = ""`). Empty means "inherit the provider's region."
- On the `"google/gemini-3.1-flash-image"` Model row, set `region="global"`. Do NOT add a region to any other model (Veo and all others inherit the provider default).

### 2. `sdk/sfvf/providers/google.py`
- There are two spots that compute the region: `region = provider.region or "us-central1"` (in the image `generateContent` path, ~line 104, and in the Veo `predictLongRunning` path, ~line 188). Change BOTH to prefer the model's own region:
  `region = model.region or provider.region or "us-central1"`
- Nothing else changes. `_endpoint` already handles `region == "global"` (hostless `https://aiplatform.googleapis.com` + `locations/global`), so the image path will build the correct global URL once the model carries `region="global"`. Veo's model.region is empty, so it still resolves to `us-central1`.

## Scope (ONLY these two files)
- `sdk/sfvf/providers/registry.py`
- `sdk/sfvf/providers/google.py`
Do NOT touch any test, other sdk files, docs/, handoff/, requirements, or CI.

## Constraints
- No new dependency. Minimal change.
- `ruff check`, `ruff format --check`, and `mypy` clean on both files.

## Acceptance criteria
1. `python -m pytest tests/integration/test_google_image.py` — all pass (image call now at the global endpoint).
2. `python -m pytest tests/integration/test_video_veo.py tests/integration/test_google_errors.py tests/sdk/test_providers_registry.py tests/sdk/test_providers_kit.py` — all still pass (Veo still us-central1; Model dataclass change breaks nothing).
3. `ruff check` + `ruff format --check` + `mypy` clean on both changed files.
4. git diff shows exactly those two files changed.
