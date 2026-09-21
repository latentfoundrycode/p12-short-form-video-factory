"""Frozen contract — web-image-sourcing increment 5: `media.web.source()` (the checked selection).

`source(query, *, subject, sources, want, consider, min_score, licence) -> list[SourcedImage]`
composes search -> fetch -> check_relevance: it searches, then in search-provider RANK ORDER fetches
each candidate and runs the VLM relevance gate, keeping the first `want` whose
`relevance.score >= min_score`. It stops once `want` pass or `consider` are exhausted (so it may
return FEWER than `want`), bounding fan-out. Each candidate's fetch + VLM check runs inside its OWN
cached `ctx.step` (design §9.5) so a resume does not repay completed fetches/checks. `consider >
_MAX_CONSIDER` raises.

These tests isolate the COMPOSE logic by monkeypatching `search`/`fetch`/`check_relevance` on the
module (search's Openverse HTTP and fetch's download/normalise are covered by their own contracts).
`ctx.paths.cache` is set because the real path uses `ctx.step`.
"""

from pathlib import Path

import pytest
from sfvf import media
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths
from sfvf.media import web as web_mod


def _ctx(tmp: Path, *, dry_run: bool = False) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            paths=ContextPaths(
                video=tmp,
                artifacts=tmp / "artifacts",
                steps=tmp / ".steps",
                shared=tmp,
                cache=tmp / "cache",  # ctx.step requires the content-addressed cache root
            ),
        )
    )


def _run(ctx: Context, fn):
    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def _cand(url: str, rank: int) -> dict:
    return {
        "source": "commons",
        "url": url,
        "thumbnail": "",
        "licence": "cc0 1.0",
        "attribution": "x",
        "width": 8,
        "height": 8,
        "title": url,
        "rank": rank,
    }


def _install(
    monkeypatch: pytest.MonkeyPatch, candidates: list[dict], scores: dict[str, float]
) -> dict[str, list]:
    """Monkeypatch search/fetch/check_relevance; record calls. scores: url -> relevance score."""
    calls: dict[str, list] = {"search": [], "fetch": [], "check": []}

    def fake_search(query, *, sources=("commons",), limit=10, licence=None):
        calls["search"].append({"query": query, "limit": limit})
        return candidates[:limit]

    def fake_fetch(candidate):
        calls["fetch"].append(candidate["url"])
        return f"web-{candidate['rank']}.png"

    def fake_check(image, *, subject, model=web_mod._VISION_MODEL):
        calls["check"].append({"image": image, "subject": subject})
        # find the candidate whose fetched path matches
        rank = int(image.split("-")[1].split(".")[0])
        url = next(c["url"] for c in candidates if c["rank"] == rank)
        s = scores[url]
        return {"relevant": s >= 0.5, "score": s, "reason": f"score {s}"}

    monkeypatch.setattr(web_mod, "search", fake_search)
    monkeypatch.setattr(web_mod, "fetch", fake_fetch)
    monkeypatch.setattr(web_mod, "check_relevance", fake_check)
    return calls


# --- compose: rank order, early stop, min_score gate -------------------------------------------


def test_source_returns_want_passing_in_rank_order_and_stops_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cands = [_cand("u0", 0), _cand("u1", 1), _cand("u2", 2)]
    calls = _install(monkeypatch, cands, {"u0": 0.9, "u1": 0.8, "u2": 0.7})
    out = _run(
        _ctx(tmp_path),
        lambda: media.web.source("q", subject="s", want=1, consider=8, min_score=0.6),
    )
    assert [si["candidate"]["url"] for si in out] == ["u0"]
    assert out[0]["path"] == "web-0.png"
    assert out[0]["relevance"]["score"] == pytest.approx(0.9)
    # early stop: once `want` pass, no further candidate is fetched/checked
    assert calls["fetch"] == ["u0"]
    assert len(calls["check"]) == 1


def test_source_skips_candidates_below_min_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cands = [_cand("u0", 0), _cand("u1", 1), _cand("u2", 2)]
    _install(monkeypatch, cands, {"u0": 0.3, "u1": 0.8, "u2": 0.9})
    out = _run(
        _ctx(tmp_path),
        lambda: media.web.source("q", subject="s", want=1, consider=8, min_score=0.6),
    )
    # u0 (0.3) fails the gate; u1 (0.8) is the first pass
    assert [si["candidate"]["url"] for si in out] == ["u1"]


def test_source_returns_multiple_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cands = [_cand("u0", 0), _cand("u1", 1), _cand("u2", 2)]
    _install(monkeypatch, cands, {"u0": 0.9, "u1": 0.4, "u2": 0.7})
    out = _run(
        _ctx(tmp_path),
        lambda: media.web.source("q", subject="s", want=2, consider=8, min_score=0.6),
    )
    assert [si["candidate"]["url"] for si in out] == ["u0", "u2"]  # u1 skipped (0.4)


def test_source_returns_fewer_than_want_when_few_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cands = [_cand("u0", 0), _cand("u1", 1)]
    _install(monkeypatch, cands, {"u0": 0.9, "u1": 0.2})
    out = _run(
        _ctx(tmp_path),
        lambda: media.web.source("q", subject="s", want=3, consider=8, min_score=0.6),
    )
    assert [si["candidate"]["url"] for si in out] == ["u0"]


def test_source_bounds_fetch_and_check_by_consider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 5 candidates available, but consider=2: at most 2 are fetched/checked (fan-out bound)
    cands = [_cand(f"u{i}", i) for i in range(5)]
    calls = _install(monkeypatch, cands, {f"u{i}": 0.1 for i in range(5)})  # none pass
    out = _run(
        _ctx(tmp_path),
        lambda: media.web.source("q", subject="s", want=3, consider=2, min_score=0.6),
    )
    assert out == []
    assert len(calls["fetch"]) <= 2 and len(calls["check"]) <= 2


def test_source_want_zero_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cands = [_cand("u0", 0)]
    calls = _install(monkeypatch, cands, {"u0": 0.9})
    out = _run(_ctx(tmp_path), lambda: media.web.source("q", subject="s", want=0, consider=8))
    assert out == []
    assert calls["fetch"] == [] and calls["check"] == []


def test_source_rejects_consider_above_the_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, [_cand("u0", 0)], {"u0": 0.9})
    with pytest.raises(ValueError):
        _run(
            _ctx(tmp_path),
            lambda: media.web.source("q", subject="s", consider=web_mod._MAX_CONSIDER + 1),
        )


# --- per-candidate cached ctx.step: a resume does not repay completed fetches/checks -----------


def test_source_caches_each_candidate_fetch_and_check_across_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cands = [_cand("u0", 0), _cand("u1", 1)]
    calls = _install(monkeypatch, cands, {"u0": 0.3, "u1": 0.8})
    ctx = _ctx(tmp_path)
    first = _run(ctx, lambda: media.web.source("q", subject="s", want=1, consider=8, min_score=0.6))
    assert [si["candidate"]["url"] for si in first] == ["u1"]
    fetches_after_first = list(calls["fetch"])
    checks_after_first = len(calls["check"])
    assert fetches_after_first, "first run must actually fetch/check"
    # a second identical run must reuse the cached per-candidate steps — no repeated fetch/check
    second = _run(
        ctx, lambda: media.web.source("q", subject="s", want=1, consider=8, min_score=0.6)
    )
    assert [si["candidate"]["url"] for si in second] == ["u1"]
    assert calls["fetch"] == fetches_after_first, "cached run must not re-fetch"
    assert len(calls["check"]) == checks_after_first, "cached run must not re-check"


# --- dry-run short-circuit stays (no gate call) ------------------------------------------------


def test_source_dry_run_short_circuits_without_calling_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cands = [_cand("u0", 0), _cand("u1", 1)]
    calls = _install(monkeypatch, cands, {"u0": 0.9, "u1": 0.9})
    out = _run(
        _ctx(tmp_path, dry_run=True),
        lambda: media.web.source("q", subject="s", want=2, consider=8),
    )
    assert len(out) == 2
    assert calls["check"] == [], "dry-run must NOT call check_relevance"
    for si in out:
        assert set(si) >= {"path", "candidate", "relevance"}
