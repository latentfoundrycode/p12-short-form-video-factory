"""Frozen contract — web-image-sourcing increment 6: the SerpApi `web` tier (paid, key-gated).

`media.web.search(..., sources=("web",))` real path calls the SerpApi Google Images API
(`GET https://serpapi.com/search?engine=google_images`) with the workflow's `SERPAPI_API_KEY`
secret, `safe=active` (safeSearch strict — the owner's chosen content-safety posture), and maps each
`images_results` item to an `ImageCandidate` tagged `source="web"`, `licence="unknown"`
(owner-decided: web-tier images may appear in produced videos). Exercised against MOCKED HTTP only —
no network, no real spend. `web.images.web` is offered ONLY when the key is configured.

Seam the adapter exposes (patched here): `sfvf.providers.serpapi._client() -> httpx2.Client`.

SerpApi images_results item -> ImageCandidate: source="web"; url=item["original"] (full-res image);
thumbnail=item["thumbnail"]; licence="unknown"; width/height from original_width/original_height;
title=item["title"]; rank=position. A null `original` is skipped; an `unsafe` item is dropped.

The SerpApi search is a PAID upstream call (SerpApi bills per successful search), so it is gated by
the SDK budget exactly like every other paid provider (design §6, invariant H21): the web tier
RESERVES against `serpapi/usd` BEFORE dispatching the HTTP request and reconciles the priced cost on
success. A missing budget config, a missing `serpapi` ceiling, or an engaged kill switch REFUSES the
call (BudgetError) before any request reaches the network — an un-budgeted paid call is a defect.
The keyless commons/Openverse tier stays free and un-metered; only the `web` tier reserves.
"""

import contextlib
import json
from pathlib import Path

import httpx2
import pytest
from sfvf import media
from sfvf._budget import BudgetError, KillSwitchEngagedError
from sfvf._runtime import reset_active, set_active
from sfvf.context import BudgetConfig, Context, ContextFile, ContextPaths
from sfvf.providers import capabilities_offered, openverse, serpapi

_BASE = "https://serpapi.com"
_KEY = "serpapi-fake-key-not-real"
_SENTINEL = object()

_RESULTS = [
    {
        "position": 1,
        "thumbnail": "https://serpapi.com/thumb/0.jpg",
        "original": "https://cdn.example.invalid/full-0.jpg",
        "original_width": 3000,
        "original_height": 2000,
        "title": "Red barn at dusk",
        "link": "https://site0.example.invalid/page",
        "source": "House Beautiful",
    },
    {
        "position": 2,
        "thumbnail": "https://serpapi.com/thumb/1.jpg",
        "original": "https://cdn.example.invalid/full-1.jpg",
        "original_width": 1600,
        "original_height": 1200,
        "title": "Barn in a field",
        "link": "https://site1.example.invalid/page",
        "source": "Flickr",
    },
]


def _budget(tmp: Path, *, kill_switch: Path | None = None, ceiling: bool = True) -> BudgetConfig:
    # A permissive per_day ceiling for the `serpapi` meter is what makes the paid web call
    # admissible (H21 needs a configured ceiling for the meter); `ceiling=False` omits it so the
    # call fails closed. `estimates` is left empty on purpose — the serpapi adapter supplies its
    # own conservative per-search estimate, exactly as the image adapters price per image.
    return BudgetConfig(
        ledger_path=tmp / "budget" / "ledger.jsonl",
        kill_switch_path=kill_switch,
        per_day={"serpapi": 1_000_000.0} if ceiling else {},
        estimates={},
    )


def _ctx(
    tmp: Path,
    *,
    secrets: dict[str, object] | None = None,
    budget: BudgetConfig | None | object = _SENTINEL,
    disabled_web_tiers: list[str] | None = None,
    dry_run: bool = False,
) -> Context:
    # Default: a permissive serpapi budget so the paid web tier is admissible. Pass budget=None to
    # exercise the fail-closed refusal (no budget config => no paid call), or an explicit config.
    # `disabled_web_tiers` is the owner governance off-switch carried on the ContextFile (DESIGN
    # §5), distinct from the workflow-controlled `settings`/`params`.
    resolved = _budget(tmp) if budget is _SENTINEL else budget
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            secrets={"SERPAPI_API_KEY": _KEY} if secrets is None else secrets,
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
            budget=None if budget is None else resolved,  # type: ignore[arg-type]
            disabled_web_tiers=disabled_web_tiers or [],
        )
    )


def _cost_events(captured: str) -> list[dict]:
    events = []
    for line in captured.splitlines():
        s = line.strip()
        if s.startswith("{"):
            try:
                obj = json.loads(s)
            except ValueError:
                continue
            if obj.get("t") == "cost":
                events.append(obj)
    return events


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx2.Request]:
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request, len(seen))

    def _client() -> httpx2.Client:
        return httpx2.Client(base_url=_BASE, transport=httpx2.MockTransport(wrapped))

    monkeypatch.setattr(serpapi, "_client", _client)
    return seen


def _run(ctx: Context, fn):
    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def _ok(_request: httpx2.Request, _n: int) -> httpx2.Response:
    return httpx2.Response(200, json={"search_metadata": {}, "images_results": _RESULTS})


# --- request shape + candidate mapping ----------------------------------------------------------


def test_web_search_hits_serpapi_google_images_and_maps_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ok)
    out = _run(
        _ctx(tmp_path),
        lambda: media.web.search("red barn", sources=("web",), limit=5),
    )
    assert len(seen) == 1
    req = seen[0]
    assert req.method == "GET"
    assert str(req.url).split("?")[0].endswith("/search")
    assert req.url.params.get("engine") == "google_images"
    assert req.url.params.get("q") == "red barn"
    assert req.url.params.get("safe") == "active", "safeSearch must be strict (owner decision)"
    assert req.url.params.get("api_key") == _KEY, "the SERPAPI_API_KEY secret drives the call"

    assert [c["url"] for c in out] == [r["original"] for r in _RESULTS]
    first = out[0]
    assert first["source"] == "web"
    assert first["licence"] == "unknown", "web-tier licence is always unknown"
    assert first["thumbnail"] == _RESULTS[0]["thumbnail"]
    assert first["title"] == _RESULTS[0]["title"]
    assert first["width"] == 3000 and first["height"] == 2000
    assert first["rank"] == 0 and out[1]["rank"] == 1
    assert first["attribution"].strip(), "a web result carries a non-empty attribution"
    json.dumps(out)


def test_web_search_sends_safe_active_content_safety(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ok)
    _run(_ctx(tmp_path), lambda: media.web.search("barn", sources=("web",)))
    assert seen[0].url.params.get("safe") == "active"


def test_web_search_returns_empty_for_a_nonpositive_limit_without_a_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ok)
    for bad in (0, -1):
        out = _run(
            _ctx(tmp_path), lambda n=bad: media.web.search("barn", sources=("web",), limit=n)
        )
        assert out == []
    assert seen == []


# --- robustness: untrusted provider payload -----------------------------------------------------


def test_web_search_skips_null_original_and_unsafe_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        {"original": None, "title": "no url"},  # null original -> skipped
        {
            "original": "https://cdn.example.invalid/nsfw.jpg",
            "unsafe": True,
            "title": "nsfw",
        },  # dropped
        {
            "original": "https://cdn.example.invalid/ok.jpg",
            "thumbnail": None,
            "title": None,
            "original_width": None,
            "original_height": None,
        },
    ]

    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(200, json={"images_results": rows})

    _install_mock(monkeypatch, handler)
    out = _run(_ctx(tmp_path), lambda: media.web.search("barn", sources=("web",)))
    assert [c["url"] for c in out] == ["https://cdn.example.invalid/ok.jpg"]
    c = out[0]
    assert c["licence"] == "unknown"
    assert c["thumbnail"] == "" and c["title"] == ""
    assert c["width"] == 0 and c["height"] == 0
    json.dumps(out)


def test_web_search_tolerates_a_non_list_images_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(200, json={"images_results": 5})

    _install_mock(monkeypatch, handler)
    out = _run(_ctx(tmp_path), lambda: media.web.search("barn", sources=("web",)))
    assert out == []


def test_web_search_raises_a_clean_error_without_leaking_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bad(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(401, json={"error": "Invalid API key"})

    _install_mock(monkeypatch, bad)
    with pytest.raises(RuntimeError) as exc:
        _run(_ctx(tmp_path), lambda: media.web.search("barn", sources=("web",)))
    assert _KEY not in str(exc.value), "the API key must never appear in the error"


def test_web_search_does_not_leak_the_key_in_a_non_auth_error_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The api_key is a QUERY-param secret. A non-401 error (here 400) surfaces the response body,
    # and _http's auth-HEADER redaction cannot see a query-param secret — so if SerpApi reflects the
    # key in that body it would leak into the error/logs. The adapter must pass the key to the
    # redactor. (The 401 path above discards the body, so it does not exercise this.)
    def reflect_key(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(400, json={"error": f"invalid api_key={_KEY}"})

    _install_mock(monkeypatch, reflect_key)
    with pytest.raises(RuntimeError) as exc:
        _run(_ctx(tmp_path), lambda: media.web.search("barn", sources=("web",)))
    assert _KEY not in str(exc.value), "the api_key must never appear in an error, even a 400 body"


# --- capability gating on the secret ------------------------------------------------------------


def test_web_capability_is_offered_only_when_the_key_is_configured() -> None:
    assert "web.images.web" in capabilities_offered({"SERPAPI_API_KEY"})
    assert "web.images.web" not in capabilities_offered(set())
    # the keyless commons capability is offered regardless
    assert "web.images.commons" in capabilities_offered(set())


# --- mixed commons+web dispatch (both tiers, URL-deduplicated) ----------------------------------


def test_mixed_commons_and_web_dispatches_both_tiers_and_dedups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A ("commons","web") request now dispatches BOTH real tiers and URL-deduplicates the union
    # (design §3.1). One url is shared by both tiers to prove the dedup keeps first-seen order.
    shared = "https://cdn.example.invalid/full-0.jpg"  # equals _RESULTS[0]["original"]

    def openverse_client() -> httpx2.Client:
        def handler(_req: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200,
                json={
                    "results": [
                        {
                            "url": shared,  # duplicate of the web tier's first hit
                            "license": "cc0",
                            "license_version": "1.0",
                            "attribution": "x",
                            "title": "commons dup",
                        },
                        {
                            "url": "https://cdn.example.invalid/commons-only.jpg",
                            "license": "by",
                            "license_version": "4.0",
                            "attribution": "y",
                            "title": "commons only",
                        },
                    ]
                },
            )

        return httpx2.Client(
            base_url="https://api.openverse.org/v1", transport=httpx2.MockTransport(handler)
        )

    monkeypatch.setattr(openverse, "_client", openverse_client)
    _install_mock(monkeypatch, _ok)  # serpapi returns _RESULTS (first url == shared)

    out = _run(
        _ctx(tmp_path), lambda: media.web.search("barn", sources=("commons", "web"), limit=5)
    )
    urls = [c["url"] for c in out]
    # commons first (rank order), then web; the shared url appears once (first-seen = commons)
    assert urls == [
        shared,
        "https://cdn.example.invalid/commons-only.jpg",
        "https://cdn.example.invalid/full-1.jpg",
    ]
    assert out[0]["source"] == "commons", "first-seen wins for a duplicate url"


def test_mixed_source_search_caps_the_merged_result_at_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each tier is queried with `limit`, but the MERGED, de-duplicated result must not exceed
    # `limit` total. Otherwise sources=("commons","web") returns up to 2*limit, and because
    # source() runs one PAID VLM check per returned candidate, source(consider=50, both tiers)
    # would fan out to ~100 paid checks — busting the signed-off 50-candidate cost ceiling.
    limit = 4

    def commons_client() -> httpx2.Client:
        def handler(_req: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200,
                json={
                    "results": [
                        {
                            "url": f"https://cdn.example.invalid/commons-{i}.jpg",
                            "license": "cc0",
                            "license_version": "1.0",
                            "attribution": "x",
                            "title": f"c{i}",
                        }
                        for i in range(limit)
                    ]
                },
            )

        return httpx2.Client(
            base_url="https://api.openverse.org/v1", transport=httpx2.MockTransport(handler)
        )

    def web_handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        rows = [
            {
                "original": f"https://cdn.example.invalid/web-{i}.jpg",
                "thumbnail": "",
                "title": f"w{i}",
                "original_width": 10,
                "original_height": 10,
            }
            for i in range(limit)
        ]
        return httpx2.Response(200, json={"images_results": rows})

    monkeypatch.setattr(openverse, "_client", commons_client)
    _install_mock(monkeypatch, web_handler)  # each tier returns `limit` distinct urls => 2*limit

    out = _run(
        _ctx(tmp_path),
        lambda: media.web.search("barn", sources=("commons", "web"), limit=limit),
    )
    assert len(out) == limit, "the merged result must be capped at `limit`, not limit-per-tier"
    assert out[0]["source"] == "commons", "first-seen (commons-first) order is preserved by the cap"


# --- budget gate: the paid SerpApi search reserves before dispatch (H21, design §6) -------------


def test_web_search_reserves_and_records_a_priced_serpapi_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A successful web search RESERVES against serpapi/usd before the request and reconciles a
    # priced cost after it — the same reserve→record discipline as the paid image/video adapters.
    seen = _install_mock(monkeypatch, _ok)
    _run(_ctx(tmp_path), lambda: media.web.search("red barn", sources=("web",), limit=5))
    assert len(seen) == 1  # the call went through (budget admitted it)

    events = _cost_events(capsys.readouterr().out)
    assert events, "a paid web search must emit a cost event"
    event = events[-1]
    assert event["meter"] == "serpapi" and event["unit"] == "usd"
    assert isinstance(event["amount"], int | float) and event["amount"] > 0
    # the reservation was reconciled to a real 'actual' ledger entry (not left dangling)
    ledger = tmp_path / "budget" / "ledger.jsonl"
    actual = [
        json.loads(line)
        for line in ledger.read_text(encoding="utf-8").splitlines()
        if line and json.loads(line).get("kind") == "actual"
    ]
    assert actual and actual[-1]["amount"] == pytest.approx(event["amount"])


def test_web_search_without_a_budget_is_refused_before_any_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No budget config at all => the paid web call fails closed (H21) BEFORE the network is touched.
    seen = _install_mock(monkeypatch, _ok)
    with pytest.raises(BudgetError):
        _run(
            _ctx(tmp_path, budget=None),
            lambda: media.web.search("barn", sources=("web",)),
        )
    assert seen == [], "a budget-refused paid call must not dispatch any HTTP request"


def test_web_search_without_a_serpapi_ceiling_is_refused_before_any_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A budget exists but has no ceiling for the serpapi meter => still fail closed, no dispatch.
    seen = _install_mock(monkeypatch, _ok)
    with pytest.raises(BudgetError):
        _run(
            _ctx(tmp_path, budget=_budget(tmp_path, ceiling=False)),
            lambda: media.web.search("barn", sources=("web",)),
        )
    assert seen == []


def test_web_search_with_the_kill_switch_engaged_is_refused_before_any_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The global kill switch must stop the paid web call — the invariant Review B named explicitly.
    kill = tmp_path / "STOP"
    kill.write_text("halt", encoding="utf-8")
    seen = _install_mock(monkeypatch, _ok)
    with pytest.raises((BudgetError, KillSwitchEngagedError)):
        _run(
            _ctx(tmp_path, budget=_budget(tmp_path, kill_switch=kill)),
            lambda: media.web.search("barn", sources=("web",)),
        )
    assert seen == []


def test_commons_only_search_needs_no_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The keyless commons tier is FREE and un-metered: a commons-only search must not require a
    # budget (only the paid web tier reserves). Proven by running it with budget=None.
    def openverse_client() -> httpx2.Client:
        def handler(_req: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200,
                json={
                    "results": [
                        {
                            "url": "https://cdn.example.invalid/commons.jpg",
                            "license": "cc0",
                            "license_version": "1.0",
                            "attribution": "x",
                            "title": "commons",
                        }
                    ]
                },
            )

        return httpx2.Client(
            base_url="https://api.openverse.org/v1", transport=httpx2.MockTransport(handler)
        )

    monkeypatch.setattr(openverse, "_client", openverse_client)
    out = _run(
        _ctx(tmp_path, budget=None, secrets={}),
        lambda: media.web.search("barn", sources=("commons",)),
    )
    assert [c["url"] for c in out] == ["https://cdn.example.invalid/commons.jpg"]


# --- billing boundary: a billed 200 whose body fails to parse must RETAIN the charge ------------
# (SerpApi bills per SUCCESSFUL search: once a 200 is received the search is billed, so a later
#  parse/mapping failure must NOT release the reserve to $0 — otherwise malformed payloads incur
#  real spend that never counts toward the ceilings. Cross-family Review B P1.)


def _ledger_entries(tmp: Path) -> list[dict]:
    ledger = tmp / "budget" / "ledger.jsonl"
    if not ledger.is_file():
        return []
    return [
        json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_web_search_retains_the_charge_when_a_billed_200_body_is_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def malformed(_request: httpx2.Request, _n: int) -> httpx2.Response:
        # HTTP 200 => SerpApi billed this search, but the body is not parseable JSON.
        return httpx2.Response(200, content=b"<<not json at all>>")

    seen = _install_mock(monkeypatch, malformed)
    # a parse failure on a billed 200 surfaces as an error (like an HTTP error), but the charge
    # must be RETAINED, never released to $0.
    with pytest.raises(RuntimeError):
        _run(_ctx(tmp_path), lambda: media.web.search("barn", sources=("web",)))
    assert len(seen) == 1  # the request WAS dispatched (200 received => billed)

    entries = _ledger_entries(tmp_path)
    reserved = [e for e in entries if e.get("kind") == "reserved" and e.get("meter") == "serpapi"]
    released = [e for e in entries if e.get("kind") == "actual" and e.get("note") == "released"]
    assert reserved, "a reservation must have been taken for the paid search"
    assert not released, "a billed 200 must NOT release the reserve to $0 on a parse failure"


# --- per-search price: the ceiling must bound REAL spend (default >= priciest standard plan) ------
# (Cross-family Review B P1: reserving/reconciling a flat $0.02 under-charges — SerpApi's priciest
#  standard plan, Starter, is $25/1k = $0.025/search, so a $0.09 ceiling that "should" admit 3
#  searches would admit 4, recording $0.08 for $0.10 of real spend. The default per-search price
#  must be >= $0.025, and an owner may override it with their plan rate via estimates["serpapi"];
#  reserve AND recorded cost must both use that amount.)


def test_serpapi_default_price_bounds_the_daily_ceiling_at_the_starter_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No configured estimate => the conservative default (>= $0.025) governs. A $0.09/day ceiling
    # admits exactly 3 searches (3*0.025 = 0.075 <= 0.09); the 4th (0.10 > 0.09) is refused before
    # dispatch. At the old $0.02 the 4th (0.08 <= 0.09) was wrongly admitted.
    seen = _install_mock(monkeypatch, _ok)
    budget = BudgetConfig(
        ledger_path=tmp_path / "budget" / "ledger.jsonl",
        per_day={"serpapi": 0.09},
        estimates={},
    )
    ctx = _ctx(tmp_path, budget=budget)
    for _ in range(3):
        assert _run(ctx, lambda: media.web.search("barn", sources=("web",)))  # admitted
    assert len(seen) == 3
    with pytest.raises(BudgetError):
        _run(ctx, lambda: media.web.search("barn", sources=("web",)))
    assert len(seen) == 3, "the 4th search exceeds $0.09 at the >=$0.025 default rate"


def test_a_configured_serpapi_rate_drives_both_the_reserve_and_the_recorded_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # When the owner configures their plan's per-search rate, BOTH the reserve (ceiling math) and
    # the recorded cost use it — not a hardcoded default. The old code reconciled a flat $0.02, so
    # any plan priced above that under-counted spend and busted the ceiling.
    seen = _install_mock(monkeypatch, _ok)
    budget = BudgetConfig(
        ledger_path=tmp_path / "budget" / "ledger.jsonl",
        per_day={"serpapi": 0.09},
        estimates={"serpapi": 0.04},  # the owner's plan rate
    )
    ctx = _ctx(tmp_path, budget=budget)
    assert _run(ctx, lambda: media.web.search("barn", sources=("web",)))
    events = _cost_events(capsys.readouterr().out)
    assert events and events[-1]["amount"] == pytest.approx(0.04), (
        "record_cost must use the configured rate, not the hardcoded default"
    )
    # the ceiling uses 0.04 too: a 2nd is admitted (0.08 <= 0.09), a 3rd refused (0.12 > 0.09)
    assert _run(ctx, lambda: media.web.search("barn", sources=("web",)))
    with pytest.raises(BudgetError):
        _run(ctx, lambda: media.web.search("barn", sources=("web",)))
    assert len(seen) == 2, "the reserve honours the configured $0.04 rate"


def test_repeated_billed_but_malformed_200s_accumulate_toward_the_serpapi_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The daily ceiling admits exactly ONE search. The first billed-but-malformed 200 must RETAIN
    # its charge, so the SECOND search is refused BEFORE any HTTP dispatch. If the reserve were
    # released on the parse failure (the defect), both would dispatch and bypass the cap.
    def malformed(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(200, content=b"garbage")

    seen = _install_mock(monkeypatch, malformed)
    budget = BudgetConfig(
        ledger_path=tmp_path / "budget" / "ledger.jsonl",
        per_day={"serpapi": 0.03},  # room for exactly one ~0.02 search
        estimates={},
    )
    ctx = _ctx(tmp_path, budget=budget)
    with pytest.raises(RuntimeError):  # first search: billed 200, malformed body, charge retained
        _run(ctx, lambda: media.web.search("barn", sources=("web",)))
    assert len(seen) == 1
    with pytest.raises(BudgetError):  # 0.02 retained + 0.02 > 0.03 => refused before dispatch
        _run(ctx, lambda: media.web.search("barn", sources=("web",)))
    assert len(seen) == 1, "the second paid search must be refused before any HTTP dispatch"


def test_web_search_releases_the_reserve_on_a_pre_dispatch_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A failure BEFORE the request is dispatched (here: building the HTTP client raises) is a
    # CONFIRMED-unbilled outcome — nothing reached SerpApi — so the reserve must be RELEASED, not
    # retained. (The billed flag must flip only at the dispatch, mirroring agents.py, so a failure
    # up to that point does not leak an estimate toward the ceilings.)
    def boom_client() -> httpx2.Client:
        raise RuntimeError("cannot construct the HTTP client")

    monkeypatch.setattr(serpapi, "_client", boom_client)
    with pytest.raises(RuntimeError):
        _run(_ctx(tmp_path), lambda: media.web.search("barn", sources=("web",)))

    entries = _ledger_entries(tmp_path)
    reserved = [e for e in entries if e.get("kind") == "reserved" and e.get("meter") == "serpapi"]
    released = [e for e in entries if e.get("kind") == "actual" and e.get("note") == "released"]
    assert reserved, "a reservation was taken before the (failed) dispatch"
    assert released, "an unbilled pre-dispatch failure must release the reserve to $0"


# --- governance off-switch: an owner may disable a web-image tier at RUNTIME (DESIGN §5) ---------
# The enabled-tier policy is carried on the run Context (owner-controlled, NOT the workflow's
# settings/params), and media.web re-checks it: a search/source targeting a disabled tier raises at
# call time, BEFORE any secret load or upstream dispatch — the SDK call is the enforcement point, so
# a workflow that calls the SDK directly cannot bypass a scan-time-only flag.


def test_web_search_refuses_a_disabled_web_tier_before_secret_or_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ok)
    # web disabled AND no key configured: the governance refusal must fire before the secret is even
    # read (so it is a policy error, not a missing-key KeyError) and before any HTTP dispatch.
    ctx = _ctx(tmp_path, secrets={}, disabled_web_tiers=["web"])
    with pytest.raises(media.web.WebTierDisabledError):
        _run(ctx, lambda: media.web.search("barn", sources=("web",)))
    assert seen == [], "a disabled tier must not dispatch any request"


def test_disabled_web_tier_is_refused_even_in_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Governance is not mode-scoped: a disabled tier is refused in dry-run too (a workflow must not
    # depend on a tier the owner has switched off).
    ctx = _ctx(tmp_path, disabled_web_tiers=["web"], dry_run=True)
    with pytest.raises(media.web.WebTierDisabledError):
        _run(ctx, lambda: media.web.search("barn", sources=("web",)))


def test_commons_still_works_when_the_web_tier_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def openverse_client() -> httpx2.Client:
        def handler(_req: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200,
                json={
                    "results": [
                        {
                            "url": "https://cdn.example.invalid/commons.jpg",
                            "license": "cc0",
                            "license_version": "1.0",
                            "attribution": "x",
                            "title": "commons",
                        }
                    ]
                },
            )

        return httpx2.Client(
            base_url="https://api.openverse.org/v1", transport=httpx2.MockTransport(handler)
        )

    monkeypatch.setattr(openverse, "_client", openverse_client)
    ctx = _ctx(tmp_path, secrets={}, budget=None, disabled_web_tiers=["web"])
    out = _run(ctx, lambda: media.web.search("barn", sources=("commons",)))
    assert [c["url"] for c in out] == ["https://cdn.example.invalid/commons.jpg"]


def test_mixed_sources_refuse_when_any_requested_tier_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ok)  # serpapi mock; commons is not mocked -> must not be hit

    def openverse_boom() -> httpx2.Client:
        def handler(_req: httpx2.Request) -> httpx2.Response:  # pragma: no cover - must not run
            raise AssertionError(
                "a request targeting a disabled tier must not dispatch either tier"
            )

        return httpx2.Client(
            base_url="https://api.openverse.org/v1", transport=httpx2.MockTransport(handler)
        )

    monkeypatch.setattr(openverse, "_client", openverse_boom)
    ctx = _ctx(tmp_path, disabled_web_tiers=["web"])
    with pytest.raises(media.web.WebTierDisabledError):
        _run(ctx, lambda: media.web.search("barn", sources=("commons", "web"), limit=5))
    assert seen == []


def test_source_refuses_a_disabled_web_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ok)
    ctx = _ctx(tmp_path, disabled_web_tiers=["web"])
    with pytest.raises(media.web.WebTierDisabledError):
        _run(ctx, lambda: media.web.source("barn", subject="a red barn", sources=("web",), want=1))
    assert seen == []


def test_web_tier_enabled_by_default_when_not_disabled(tmp_path: Path) -> None:
    # No disabled tiers => the Context reports every tier enabled (design default: on with key).
    ctx = _ctx(tmp_path)
    assert ctx.web_tier_enabled("web") is True
    assert ctx.web_tier_enabled("commons") is True
    ctx_off = _ctx(tmp_path, disabled_web_tiers=["web"])
    assert ctx_off.web_tier_enabled("web") is False
    assert ctx_off.web_tier_enabled("commons") is True


# --- sources is a SUBSET: a repeated tier must not dispatch/charge the same paid search twice -----


def test_duplicate_sources_dispatch_and_charge_each_tier_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # sources has set semantics ("a subset of (commons, web)"); sources=("web","web") must dispatch
    # the paid SerpApi search ONCE and record ONE charge, not two, then behave like ("web",).
    seen = _install_mock(monkeypatch, _ok)
    out = _run(
        _ctx(tmp_path),
        lambda: media.web.search("barn", sources=("web", "web"), limit=5),
    )
    assert len(seen) == 1, "a repeated tier must dispatch only once"
    events = _cost_events(capsys.readouterr().out)
    assert len(events) == 1, "a repeated tier must not double-charge the paid search"
    assert [c["url"] for c in out] == [r["original"] for r in _RESULTS]


def test_duplicate_mixed_sources_are_canonicalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ok)
    commons_calls = {"n": 0}

    def openverse_client() -> httpx2.Client:
        def handler(_req: httpx2.Request) -> httpx2.Response:
            commons_calls["n"] += 1
            return httpx2.Response(
                200,
                json={
                    "results": [
                        {
                            "url": "https://cdn.example.invalid/commons.jpg",
                            "license": "cc0",
                            "license_version": "1.0",
                            "attribution": "x",
                            "title": "c",
                        }
                    ]
                },
            )

        return httpx2.Client(
            base_url="https://api.openverse.org/v1", transport=httpx2.MockTransport(handler)
        )

    monkeypatch.setattr(openverse, "_client", openverse_client)
    _run(
        _ctx(tmp_path),
        lambda: media.web.search("barn", sources=("commons", "web", "commons"), limit=5),
    )
    assert commons_calls["n"] == 1, "commons dispatched once despite the repeat"
    assert len(seen) == 1, "web dispatched once despite the repeated commons"


# --- SerpApi cache hits are FREE: a `search_metadata.status == "Cached"` 200 is not charged -------


def _cached_ok(_request: httpx2.Request, _n: int) -> httpx2.Response:
    # SerpApi serves a repeated query from its cache and marks it free with status "Cached".
    return httpx2.Response(
        200, json={"search_metadata": {"status": "Cached"}, "images_results": _RESULTS}
    )


def test_a_cached_serpapi_hit_bills_zero_but_records_the_fresh_price(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A cached hit is FREE (no budget consumed) but must still teach cost forecasting the fresh
    # per-search price: emit a cost event with the normal price flagged `cached=True` (which the
    # supervisor counts toward the `uncached` forecast total but NOT toward `actual` spend), while
    # reconciling the budget LEDGER to $0. Emitting $0 with cached=False (the bug) would teach the
    # forecaster that fresh searches are free.
    seen = _install_mock(monkeypatch, _cached_ok)
    out = _run(_ctx(tmp_path), lambda: media.web.search("barn", sources=("web",), limit=5))
    assert len(seen) == 1
    assert [c["url"] for c in out] == [r["original"] for r in _RESULTS]  # candidates still mapped
    events = [e for e in _cost_events(capsys.readouterr().out) if e["meter"] == "serpapi"]
    assert events, "a cost event is still emitted for forecasting"
    ev = events[-1]
    assert ev["amount"] > 0.0, "the FRESH per-search price is recorded for forecasting, not $0"
    assert ev["cached"] is True, "a cached hit is flagged cached=True (excluded from actual spend)"
    # the budget LEDGER, though, is reconciled to $0 — a free cached hit consumes no ceiling
    actual = [
        e
        for e in _ledger_entries(tmp_path)
        if e.get("kind") == "actual" and e.get("meter") == "serpapi"
    ]
    assert actual and all(e["amount"] == 0.0 for e in actual)


def test_repeated_cached_searches_do_not_exhaust_the_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With free cached hits reconciled to $0, a tight $0.05/day ceiling never accrues, so repeated
    # cached searches all proceed. (At the buggy full-charge behaviour the 3rd would be refused.)
    seen = _install_mock(monkeypatch, _cached_ok)
    budget = BudgetConfig(
        ledger_path=tmp_path / "budget" / "ledger.jsonl",
        per_day={"serpapi": 0.05},
        estimates={},
    )
    ctx = _ctx(tmp_path, budget=budget)
    for _ in range(5):
        assert _run(ctx, lambda: media.web.search("barn", sources=("web",), limit=5))
    assert len(seen) == 5, "free cached searches must not consume the ceiling"


def _cached_malformed(_request: httpx2.Request, _n: int) -> httpx2.Response:
    # A cached (free) 200 whose result has a non-numeric dimension: the mapping's int() will raise.
    return httpx2.Response(
        200,
        json={
            "search_metadata": {"status": "Cached"},
            "images_results": [
                {
                    "original": "https://cdn.example.invalid/x.jpg",
                    "original_width": "not-a-number",
                    "original_height": 10,
                    "title": "x",
                    "thumbnail": "",
                }
            ],
        },
    )


def test_a_cached_response_is_free_even_if_result_mapping_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A cached response is KNOWN free once parsed; reconciliation to $0 must happen BEFORE the
    # fallible mapping loop, so a malformed field can't leave the full reservation charged (which
    # would let repeated free-but-malformed cache hits exhaust the ceiling). Review B P1.
    _install_mock(monkeypatch, _cached_malformed)
    # the malformed dimension may raise; the billing must still be correct regardless
    with contextlib.suppress(Exception):
        _run(_ctx(tmp_path), lambda: media.web.search("barn", sources=("web",)))
    entries = _ledger_entries(tmp_path)
    reserved = [e for e in entries if e.get("kind") == "reserved" and e.get("meter") == "serpapi"]
    actual = [e for e in entries if e.get("kind") == "actual" and e.get("meter") == "serpapi"]
    assert reserved, "a reservation was taken for the paid search"
    assert actual and all(e["amount"] == 0.0 for e in actual), (
        "a cached hit is free and must reconcile to $0 even when result mapping fails"
    )
