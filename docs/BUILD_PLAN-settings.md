# Build plan — Settings tab (audit fix F1)

Replaces the §8.7 Settings stand-in (frontend/src/components/PlaceholderView.tsx, "Arrives in
a later stage") with a real Settings tab. Owner-approved 2026-09-27 ("build the full Settings
tab", "proceed with the current build plan"). Change cycle: Sensational Science News, Stage F1.
Revised after plan-critic (B1-B4, S1-S4, C1-C3).

## Scope (from PRD §8.7, mockup screen "Settings")

In scope:
- **API keys & connections (R-066)** — a GUI to see which provider keys are configured, set or
  replace a key, and clear one. Values live in the existing encrypted store
  (app/core/secrets.py: SecretStore.names/set/delete); the GUI NEVER displays a stored value,
  only whether a name is configured. The encryption state is deliberately not shown (§8.7).
- **Global defaults (R-068)** — edit the step silence limit (seconds), the default concurrency
  (videos) and default step concurrency (parallel steps per video), and the maximum cheap-cache
  size (bytes). Persisted in a new app-settings store, and **actually consumed** at the sites
  named under F1b (not merely stored).

Owner decision needed (escalated 2026-09-27 — do NOT self-defer, rule 44 / KP-029):
- **R-067 (MCP connections)** — the mockup's "Connections" panel exists only for Higgsfield,
  which the owner dropped 2026-09-27 (R-153). No MCP-based provider remains, so there is nothing
  to authenticate against. The owner must choose: record R-067 `deferred — owner <date>` (build
  when an MCP provider returns), or ask for the browser-login infrastructure built speculatively.
  Until answered, F1c must not run completion-check --mode done as a pass criterion for R-067.
  The Connections panel renders a genuine empty state ("no service connections require sign-in"),
  which is real content, not a placeholder component.

Out of scope (recorded, not stand-ins):
- **Disk thresholds** — fixed by spec (20 GB warn / 5 GB refuse), not user-configurable; their
  enforcement is R-072/R-158, separate reliability increments, not the Settings tab.

## Design

Backend (Python, FastAPI; follows app/api/*.py + app/core/*_config.py):
- **Unlocked store at request time (B1).** app/main.py resolves secrets ONCE at startup and keeps
  only the decrypted dict on `application.state.secrets`; the passphrase is discarded. Writes need
  the passphrase to re-encrypt. Decision: when the app starts from an env passphrase, retain a
  live `SecretStore` (holding the passphrase) on `application.state.secret_store` for the process
  lifetime — the passphrase is already entered at start and this is a single-user local app, so
  its presence in the server process for the session is acceptable and matches §8.7's
  start-time-passphrase model. When the app was started via the injected-secrets path (no store /
  no passphrase, e.g. tests), the store is absent and secret-write endpoints return a clear,
  value-free 409 ("secret store is locked; restart with SFVF_SECRETS_PASSPHRASE to edit keys").
- **Freshness on mutation (B2).** After a successful set/delete, refresh `application.state.secrets`
  from the live store AND rebuild the RegistryHolder so `_offered` capabilities and
  `provider_configured` recompute — so a key the user just set makes its provider immediately
  configured/offered without a restart. GET /api/settings reads the live store's names so it never
  disagrees with the registry.
- **New app-settings store.** `app/core/app_settings.py`: an AppSettings persisted as JSON under
  DATA_ROOT (imported from **app/paths.py**, not app.core.paths — C1), holding
  {silence_limit_seconds, default_concurrency, default_step_concurrency, cache_max_bytes}. Load
  tolerates a missing/corrupt file (returns defaults, never raises). Each field validated
  (positive, finite, sane bounds) on write.
- **Resolver precedence, with the NEW env vars named (S2).** Precedence per field is
  **explicit env var > stored setting > built-in default**. Env vars: `SFVF_CACHE_MAX_BYTES`
  (existing — app/core/cache_config.py), and NEW `SFVF_SILENCE_LIMIT_SECONDS`,
  `SFVF_DEFAULT_CONCURRENCY`, `SFVF_DEFAULT_STEP_CONCURRENCY`. cache_config.cache_max_bytes()
  gains the stored-value middle tier; new resolvers app_settings.silence_limit_seconds() /
  default_concurrency() / default_step_concurrency() follow the same three-tier shape.
- **Secret-name allowlist (S3).** PUT accepts a name only if it is a built-in provider secret
  name (registry) OR a `requires_keys` entry of an installed workflow — so a workflow's custom key
  is configurable from the GUI, not only the terminal. Unknown names and empty values are rejected.
- **`app/api/settings.py` router** (included in app/main.py):
  - `GET /api/settings` -> {providers:[{id,name,secret_names,configured}], allowed_secret_names,
    configured_secret_names, defaults:{field: {effective, source: env|stored|default}}}. Never a value.
  - `PUT /api/settings/secrets/{name}` {value} -> allowlist-check, SecretStore.set, refresh state
    + registry; returns new configured status.
  - `DELETE /api/settings/secrets/{name}` -> SecretStore.delete wrapped to be **idempotent**
    (catch KeyError -> success; secrets.py:59 raises on missing) (S1); refresh state + registry.
  - `PUT /api/settings/defaults` {fields...} -> validate + persist via AppSettings.
  - Inherits the existing csrf_guard middleware; single-user-local trust model (no new auth).

Frontend (React/TS; follows frontend/src/components/LibraryView.tsx + the api client):
- Replace the `settings` branch (App.tsx -> PlaceholderView) with a real `SettingsView`; delete
  PlaceholderView so no stand-in remains (completion-check --mode done clean for R-066/068).
- "API keys": one row per allowed secret name (provider/workflow, configured/missing pill); a
  write-only masked input to set/replace and a Clear button. No value shown.
- "Connections (MCP)": empty state (see R-067 owner decision).
- "Global defaults": number fields for the four defaults with units, each showing the effective
  value and its source; when an env var overrides, the field is read-only with a note. Save action.
- **Defaults are seeded from GET /api/settings at the consuming sites (B3):** RunLaunchForm and
  ScheduleView seed their concurrency/step-concurrency initial values from the stored defaults
  instead of the hard-coded `1`.

## Increments (RED-first; each: frozen tests -> confirm RED -> brief -> delegate -> Review A + cross-family Review B -> gate -> merge). Each brief states the RED-first methodology so added frozen tests are not misread as gate-gaming (S4); F1b/F1c only ADD tests, never rewrite F1a's frozen contract.

- **F1a — Secrets management API + live store + freshness.** app/api/settings.py GET + PUT/DELETE
  secrets; live SecretStore on app.state (B1); refresh state + rebuild registry on mutation (B2);
  idempotent delete (S1); allowlist = provider secrets ∪ workflow requires_keys (S3). Frozen:
  tests/api/test_settings_api.py — GET lists names never values; set makes a provider configured
  AND immediately offered (registry rebuilt); delete idempotent; unknown-name / empty-value
  rejected; locked-store (injected path) returns the value-free 409; a workflow requires_keys name
  is settable. Satisfies: R-066 (backend).
- **F1b — Global defaults store, resolvers, and real wiring.** app/core/app_settings.py + the three
  new resolvers + cache_config middle tier; wire the defaults into the REAL consumers: app/core/
  supervisor.run_request (silence_limit_default, step_concurrency) and app/api/runs.py admit_run
  (accept + pass silence + step_concurrency; seed concurrency default); GET/PUT defaults endpoints.
  Frozen: tests/core/test_app_settings.py (persist/round-trip; corrupt -> defaults; validation
  bounds; env-var precedence over stored) + tests/api/test_settings_api.py additions (defaults
  GET/PUT; admit_run applies the stored silence/step-concurrency). Satisfies: R-068.
- **F1c — Settings tab frontend.** SettingsView replaces the PlaceholderView settings branch and
  PlaceholderView is deleted; drives F1a/F1b APIs; RunLaunchForm/ScheduleView seed defaults from
  GET /api/settings. Frozen/added: a frontend test per state (loaded / saving / error /
  store-locked) reachable through the real render path (C3); "matches mockup screen Settings"
  checked against docs/SFVF_UI_Mockup.html §v-settings (C2); passes the design detector with no
  primary findings; completion-check --mode done shows no stand-in for R-066/068. Satisfies:
  R-066 (UI), R-068 (UI).

## Traceability
Satisfies R-066, R-068. R-067 awaits the owner's dated decision (above) before F1c's --mode done
criterion applies to it. The R-IDs here are named so completion-check --mode plan traces them at
F1c close.
