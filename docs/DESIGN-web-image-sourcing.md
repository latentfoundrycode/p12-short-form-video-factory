# DESIGN — Web image sourcing (SFVF core capability)

Status: **SIGNED OFF 2026-09-21** (v3). v2 folded in the plan-critic pass; v3 folds in the increment-1
cross-family Review B (source() returns an enriched result carrying provenance; library intake model;
dry-run/tier semantics; increment-1 scope = vocabulary only). The vision-model default, `min_score`,
and the `consider`/`want` fan-out defaults are accepted-but-revisitable (owner approved proceeding on
the proposed defaults; revisit at increment 4 / the §10 web-tier decisions). Depends on `agents.vision`
(merged, PR #139).

## 1. Goal

Give any workflow a first-class way to **find images on the web, download them safely, and keep only
the ones a vision model confirms are relevant** to what was being looked for. Sourcing widens material
beyond generation (real photos, plates, reference art); the **checked** selection is the value — a raw
download is worthless until a VLM says it fits. SFVF-core (a new SDK surface + adapters), opt-in per
workflow via `requires_capabilities` — not baked into one workflow. (Same principle as
multi-provider-media-is-core.)

## 2. Owner decisions locked at sign-off

- **Both sourcing tiers.** Licensed/commons AND general web search are both provided; a workflow uses
  one or both. (Owner, 2026-09-21.)
- **VLM relevance check is an SFVF-provided feature** using a sufficiently capable vision model. (Owner.)
- **Cost rides the existing per-run/per-day budget gate** — no new budget concept. (Owner.)

## 3. SDK surface (`sfvf.media.web`)

Two layers so workflows compose freely ("in tandem") or take the easy path. `ImageCandidate` and
`Relevance` are `TypedDict`s (like `agents.Source`), read by subscript.

### 3.1 Low-level — search / fetch / check

```python
search(query, *, sources=("commons",), limit=10, licence=None) -> list[ImageCandidate]
fetch(candidate) -> str                       # workspace-relative path; downloads + sanitises
check_relevance(image, *, subject, model=VISION_MODEL) -> Relevance   # the SFVF VLM gate
```

- `sources`: a non-empty tuple of `"commons"` and/or `"web"` (an empty or unknown tier is a
  `ValueError`). Passing both merges and **URL-deduplicates** results (content-hash dedup is
  impossible pre-download — bytes aren't in hand yet; content-identical downloads instead converge in
  the content-addressed library, §8). A stub/real candidate's `source` and `licence` reflect the tier
  it came from (`web`-tier → `licence="unknown"`).
- `ImageCandidate` TypedDict: `source`, `url`, `thumbnail`, `licence` (SPDX-ish or `"unknown"`),
  `attribution`, `width`, `height`, `title`, `rank` (search-provider rank — NOT relevance, which is
  unknown until `check_relevance` runs).
- `fetch()` downloads **only the candidate's own image URL** (no crawling) into `ctx.paths.video`
  through the untrusted-bytes pipeline (§7), and returns a workspace-relative **`str`** path (the same
  shape `media.image.generate()` returns, so it drops straight into `agents.llm(attach=[...])`). The
  on-disk name is `web-{sha8(url|bytes)}.{ext}` from the **validated** extension — never derived from
  the raw URL (traversal/null-byte/length risk).
- `check_relevance()` shows the image to a vision model via `agents.llm(attach=[image], schema=...)`
  and returns `Relevance` = `{relevant: bool, score: float, reason: str}`. `subject` is the
  plain-language description of what the workflow wanted.

### 3.2 High-level — source-and-check in one call

```python
source(query, *, subject, sources=("commons",), want=1, consider=8,
       min_score=0.6, licence=None) -> list[SourcedImage]
```

`source()` returns an **enriched** result so the caller keeps full provenance (path alone loses where
the image came from and why it was kept):

```python
class SourcedImage(TypedDict):
    path: str                # workspace-relative downloaded image
    candidate: ImageCandidate  # source/url/licence/attribution/… of the hit that was kept
    relevance: Relevance     # the VLM verdict (score/reason) that passed the gate
```

Searches, fetches candidates in **search-provider rank order** (relevance is unknown pre-check; no
recency default), runs `check_relevance` on each, and returns the first `want` that pass `min_score` —
the "checked selection" primitive. `want` is clamped to `>= 0`; it stops fetching/checking once `want`
pass or `consider` are exhausted (so it may return FEWER than `want` when fewer qualify), bounding
fan-out. `consider`/`want` have conservative defaults (§10; fan-out is the cost knob). **Dry-run:**
`source()` short-circuits to `want` deterministic `SourcedImage` stubs and must NOT call the relevance
gate (a dry-run has no VLM to assess with); each stub carries a passing `relevance` stub so a workflow
exercises its happy path. `check_relevance()` dry-run likewise returns a passing stub verdict
(`relevant=True, score=1.0, reason="dry-run stub"`) — the dry-run-stub convention (return usable
happy-path values so downstream wiring runs), same as `media.image.generate()` returning a real stub
image. `search`/`fetch` return deterministic stub candidates/images, no network.

## 4. Providers / adapters

| Tier | Adapter | Notes |
|---|---|---|
| `commons` | **Openverse** (primary) | Free API; aggregates CC + public-domain; rich per-image licence + attribution. |
| `commons` | **Wikimedia Commons** (fast-follow) | Free; licence + author metadata. |
| `web` | **one paid image-search API** — Bing Image Search / SerpAPI / Google Programmable Search | Broad coverage; **licence unknown per image** → asset flagged `licence="unknown"`. Paid → metered (§6). **safeSearch forced on** (§7). Which provider is a sign-off sub-decision (§10). |

Registered like the media providers; each advertises the relevant capability (§5) and its secret
name(s). `commons` needs no key (or a free one); `web` needs the chosen provider's key via
`requires_keys` + SecretStore.

## 5. Capability vocabulary + gating (split by tier for real governance)

- Add **`web.images.commons`** and **`web.images.web`** to `KNOWN_CAPABILITIES` (two capabilities, not
  one). Rationale: the `commons` tier is keyless, so a single `web.images` would be
  `capabilities_offered`-true unconditionally (`all([]) == True`) with no way for an owner to permit
  commons but forbid the paid/unknown-licence web tier. Splitting makes the gate real: `web.images.web`
  is offered only when the paid provider's key is configured; `commons` when its provider is enabled.
- A workflow declares whichever tier(s) it uses, plus `agents.vision` for `check_relevance`.
- **Governance off-switch:** an owner setting to disable the `web` tier entirely (env/registry flag)
  even when a key is present — so web sourcing can be turned off org-wide without unsetting secrets.

## 6. Budget (reuse the existing gate — with two real modelling gaps to close)

- `commons` search: free → zero-cost meter (observability only).
- `check_relevance` VLM calls: already metered — `agents.llm` on OpenRouter.
- `web` search: metered through `_budget`. **Modelling gap (S2):** paid metering today reads a
  `PriceHint` off **`Model`** rows via `adapter.image_price(model, size)`; a search API has no model
  and bills **per query / per 1000 queries** (a basis no `PriceHint.basis` covers). The design resolves
  this by giving the web adapter a **synthetic search "model" row** carrying a per-query price, and a
  new `basis="per_call"`. Because `_budget_reserve` **fails closed** (raises unless the meter has a
  configured ceiling AND a positive estimate), shipping the web tier REQUIRES a budget-config entry for
  its meter — recorded as an operational item in increment 6.
- **HARD prerequisite (S1):** the `agents.llm` budget-reserve-leak (task_1a4cc2f0) MUST land before
  increment 4. `_post_chat_completion` reserves via the bare `_budget_reserve` and only reconciles on
  the 200 path, so a failed VLM check leaks its reserve; `source(consider=8)` runs up to 8 checks per
  call, so one flaky sourcing call could leak up to 8 reserves and brick the shared `openrouter` meter
  for the run. The fix pattern already exists (`ctx._budget_reserved`, H52). Ordered before increment 4.

## 7. Safety — untrusted web content (the crux; a dedicated designed component, not "reuse H51")

Bytes AND URLs are untrusted and attacker-influenceable. Unlike `agents.vision` `attach` (trusted
workflow paths, suffix allow-list), here the guards are content-based and network-hardened.

### 7.1 SSRF / URL guard (its own component — H51 does NOT transfer)
H51/H53 is an allow-list to one first-party host (`*.bfl.ai`); here hosts are the whole internet, so
allow-listing is impossible and a deny-list on the **resolved IP** is required:
- Resolve the host, then **reject** private (RFC1918), loopback, link-local (169.254/fe80), ULA
  (fc00::/7), CGNAT (100.64/10), IPv4-mapped-IPv6, and octal/hex/decimal-encoded address forms.
- **Pin the connection to the validated IP** (or re-validate at connect) to defeat **DNS
  rebinding/TOCTOU** — a host that resolves public at check time but private at socket time.
- **Close H53(a) explicitly:** validate the SAME URL object the HTTP client will use (no
  urlsplit-vs-client parser differential); re-check `response.request.url`/the connect target.
- **Redirects:** disabled by default and followed manually, re-validating every hop against the
  resolved-IP deny-list. https-only.

### 7.2 Byte pipeline
- **Streaming byte cap** on download (reject once the ceiling is exceeded mid-stream).
- **Allowed types, enumerated:** png / jpeg / webp / (static) gif — mirroring `agents._IMAGE_MIME`.
  **SVG is excluded** (XML → XXE/SSRF-on-render, no reliable magic bytes). Validate by **magic bytes**,
  not suffix (untrusted source).
- **Decompression/pixel-bomb bound (B2):** cap decoded pixels (`Image.MAX_IMAGE_PIXELS` /
  width×height) and reject before allocating the bitmap; a 20 KB file can decode to gigapixels — the
  byte cap does not protect the decode. Reject animated GIF/APNG frame bombs (bound frames or take
  frame 0).
- **Re-encode / normalise, then DISCARD the originals:** decode and re-encode to a canonical image
  (strip EXIF/metadata/trailing data); the original bytes are never stored in the library or served.
  This — not the magic-byte check alone — is what defeats polyglot/EXIF-tracker/embedded payloads.

### 7.3 Content safety (B3 — relevance ≠ safety)
`check_relevance` gates relevance only; a relevant image can be NSFW/illegal/trademarked and would
pass. For a system that PUBLISHES video:
- Force **safeSearch=strict** on the `web` tier (Bing/SerpAPI/Google all expose it).
- A **safety disposition** step (initially: safeSearch + record source for audit; optionally a VLM/
  moderation safety pass as a fast-follow). The owner sets the web-tier content-safety posture (§10).

### 7.4 Provenance
Library descriptor records `source`, `source_url`, `licence`, `attribution`; `web`-tier assets are
flagged `licence="unknown"` so a workflow/owner decides whether they may appear in a produced video
(§10.3).

## 8. Library intake (the WORKFLOW owns the put; the SDK hands back provenance)

The library contract constrains how intake must work, so `media.web` does NOT call `ctx.library.put`
itself:
- **Facets must be workflow-declared.** `library.put` rejects an undeclared facet key
  (`LibraryError`), so `source`/`licence`/`attribution`/`subject`/`relevance_score` must be declared in
  the workflow's manifest `library.facets`. A workflow that wants sourced images in its library
  declares those facets; the SDK cannot invent them.
- **Writes belong in `prepare()`, not concurrent `run()`.** Per the SDK's write-in-prepare rule,
  sourcing-then-intake is a `prepare()`-time activity; `run()` reads the library.
- **The SDK returns provenance, the workflow writes it.** `source()` returns `list[SourcedImage]`
  (path + candidate + relevance), so the workflow does
  `ctx.library.put(key, si["path"], facets={"source": si["candidate"]["source"], "licence":
  si["candidate"]["licence"], …, "relevance_score": si["relevance"]["score"]}, description=…)` with
  its declared facets. This keeps library policy with the workflow and avoids the undeclared-facet
  conflict.
- **Reuse is not automatic from content-addressing.** Identical bytes converge to one blob, but a
  fresh run still pays for search + fetch + VLM unless it FIRST calls `ctx.library.find(...)` and
  sources only on a miss. The reuse pattern (find-before-source) is the workflow's, shown in the
  worked example. Note: a content-identical re-`put` keeps the first descriptor, so the FIRST intake's
  provenance wins — acceptable (same bytes, same image), but the workflow should prefer find-then-reuse
  over blind re-source.

This intake model is exercised by increment 5 (`source()`), not the increment-1 skeleton.

## 9. Build increments (each a gated RED→GREEN loop)

0. **Prerequisite:** land `agents.llm` budget-reserve-leak fix (task_1a4cc2f0) — ordered before #4.
1. **Contract + surface skeleton (VOCABULARY ONLY — no provider yet)** — `media.web` module,
   `ImageCandidate`/`Relevance`/`SourcedImage` TypedDicts, `web.images.commons`/`web.images.web` in
   KNOWN_CAPABILITIES, dry-run stubs (incl. `source()` short-circuit), real paths raise
   `NotImplementedError`. NO provider row this increment (advertising a capability whose real path is
   unbuilt is worse than deferring it), so the tests assert the two capabilities are currently
   **unavailable**. The provider that OFFERS `web.images.commons` — and the availability flip — arrive
   with the real adapter in increment 2.
2. **`commons` tier (Openverse)** — real search + candidate mapping (licence/attribution), the
   Openverse provider row (keyless) advertising `web.images.commons` + the availability flip, mocked
   HTTP contract; then a free live smoke. Wikimedia fast-follow.
3a. **URL/SSRF guard + safe download** — resolved-IP deny-list, IP-pinned connect, per-hop redirect
   re-validation, streaming byte cap. Adversarial tests: private/loopback/link-local/CGNAT IP,
   encoded-IP forms, DNS-rebinding, redirect-to-internal, oversize stream.
3b. **Byte validation + normalise** — magic-byte type gate (SVG excluded), pixel-bomb bound,
   animation bound, decode→re-encode→strip, content-hash filename, discard originals. Adversarial
   tests: pixel bomb, polyglot, EXIF, wrong-magic, animated bomb.
4. **`check_relevance()`** — VLM gate over `agents.vision` with a structured schema; relevant vs
   irrelevant scoring against mocked vision responses; live smoke. (After prerequisite #0.)
5. **`source()` high-level** — compose search→fetch→check with early stop + library intake; dry-run
   short-circuit.
6. **`web` tier (chosen paid provider)** — search adapter + synthetic price row + budget-config meter;
   forced safeSearch; `licence="unknown"` flagging; metered; live smoke. (After owner picks provider.)

Each increment: frozen RED contract → pinned builder → scope-check → Review A (diff-reviewer +
security-auditor — mandatory on 3a/3b/4/6 — + secret-sentinel) → cross-family Review B → CI gate →
self-merge on the four-condition gate. Live smokes are attended (a mock proves the path, never the
contract).

## 10. Open sub-decisions for sign-off

1. **Which paid `web`-tier provider** (Bing Image Search / SerpAPI / Google Programmable Search) — or
   defer the `web` tier and ship `commons` first, adding `web` when you pick a provider + fund a key.
2. **Default vision model** for `check_relevance` ("sufficiently intelligent" — a strong OpenRouter
   multimodal model); default `min_score` (proposed 0.6) and default `consider`/`want` fan-out caps
   (proposed `consider=8`, `want=1`) — the fan-out is the main cost lever.
3. **Legal posture for `licence="unknown"` (web-tier) images** — may they appear in produced videos,
   or reference-only (guide generation) until a human clears them?
4. **Content-safety posture for web-tier imagery** — safeSearch-strict only, or also a VLM/moderation
   safety pass before an image may enter the library? (Published-video risk.)
5. **PII / likeness** — may web-sourced images of identifiable people appear in published videos
   (GDPR / rights-of-publicity), or are they excluded/blurred/reference-only?

## 11. Non-goals (this stage)

Video/clip sourcing; full-site crawling; a general scraping framework; licence *purchasing*. Sourcing
is limited to the candidate URLs the search adapters return.
