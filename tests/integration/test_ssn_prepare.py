"""TASK-SSN-C2 contract: prepare() builds a trusted research pool and picks N distinct subjects.

prepare() runs ONCE (before the parallel per-video workers, rev-5), so it selects ALL N subjects
(N = ctx.video_count) in one pass: query `agents.research` with `site:` hints for the curated
allowlist, POST-FILTER the returned `Source.url` to the allowlist (host + path-prefix), score the
pool for lay-audience captivation via `agents.llm`, and pick N DISTINCT subjects that are not in
the cross-run library dedup list (a value asset) and not duplicates of each other -- then append
the N to that dedup list and return `{"subjects": [...], "sources": {...}}`. A truly empty
on-allowlist pool on a REAL run is a clean failure (RuntimeError), never a fabricated subject. In
dry-run (canned off-list research) prepare still yields N subjects so the pipeline rehearses --
that path is covered by the C1 dry-run integration test; here we drive the REAL logic in-process
with mocked agents.

Supervisor-authored frozen contract (RED-first); the builder implements the workflow prepare().
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths

_WF = Path(__file__).resolve().parents[2] / "workflows" / "sensational-science-news"


def _load_main():
    spec = importlib.util.spec_from_file_location("ssn_main_prepare_ut", _WF / "main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ctx(tmp: Path, *, video_count: int, dry_run: bool = False) -> Context:
    (tmp / "01" / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp / "01" / ".steps").mkdir(parents=True, exist_ok=True)
    (tmp / "cache").mkdir(parents=True, exist_ok=True)
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            workflow_id="sensational-science-news",
            video_count=video_count,
            paths=ContextPaths(
                video=tmp / "01",
                artifacts=tmp / "01" / "artifacts",
                steps=tmp / "01" / ".steps",
                shared=tmp / "01",
                cache=tmp / "cache",
                library=tmp / "lib",
            ),
        )
    )


def _src(main, url: str, title: str):
    # Build a Source-shaped dict the way the SDK does (agents.Source TypedDict: title/url/snippet).
    return {"title": title, "url": url, "snippet": title}


# --- allowlist post-filter (pure) ---------------------------------------------------------------


def test_allowlist_filter_keeps_on_list_drops_off_list() -> None:
    main = _load_main()
    sources = [
        _src(main, "https://www.nature.com/articles/x", "on: nature"),
        _src(main, "https://phys.org/news/y", "on: phys"),
        _src(main, "https://evil.example.com/nature.com/fake", "off: lookalike"),
        _src(main, "https://www.bbc.com/news/science_and_environment/z", "on: bbc science path"),
        _src(main, "https://www.bbc.com/sport/football", "off: bbc wrong path"),
    ]
    kept = {s["url"] for s in main._allowlist_filter(sources)}
    assert "https://www.nature.com/articles/x" in kept
    assert "https://phys.org/news/y" in kept
    assert "https://www.bbc.com/news/science_and_environment/z" in kept
    assert "https://evil.example.com/nature.com/fake" not in kept  # host, not substring
    assert "https://www.bbc.com/sport/football" not in kept  # path-prefixed entry not matched


# --- subject selection in prepare() (mocked agents, in-process) ----------------------------------


def _patch_agents(monkeypatch, main, *, sources, chosen):
    calls: dict[str, int] = {"research": 0, "llm": 0}

    def _research(query):
        calls["research"] += 1
        return list(sources)

    def _llm(prompt, *, agent, model, schema=None, attach=None):
        calls["llm"] += 1
        return {"subjects": list(chosen)}

    monkeypatch.setattr(main.agents, "research", _research)
    # The captivation LLM returns a structured selection; the workflow must still enforce dedup /
    # distinctness itself (not trust the model), so tests feed a selection and check the guarantees.
    monkeypatch.setattr(main.agents, "llm", _llm)
    return calls


def test_prepare_selects_n_distinct_subjects(tmp_path: Path, monkeypatch) -> None:
    main = _load_main()
    sources = [
        _src(main, "https://www.nature.com/a", "A finding"),
        _src(main, "https://phys.org/b", "B finding"),
        _src(main, "https://www.science.org/c", "C finding"),
    ]
    calls = _patch_agents(
        monkeypatch, main, sources=sources, chosen=["A finding", "B finding", "C finding"]
    )
    ctx = _ctx(tmp_path, video_count=3)
    token = set_active(ctx)
    try:
        shared = main.prepare(ctx)
    finally:
        reset_active(token)
    subjects = shared["subjects"]
    assert calls["research"] >= 1, "prepare must consult agents.research, not a placeholder"
    assert len(subjects) == 3
    assert len(set(subjects)) == 3  # distinct
    # the subjects are the (allowlist-filtered, deduped) captivation selection, not fabricated
    assert set(subjects) == {"A finding", "B finding", "C finding"}


def test_prepare_excludes_cross_run_dedup_list(tmp_path: Path, monkeypatch) -> None:
    main = _load_main()
    sources = [_src(main, "https://www.nature.com/a", "Old finding")]
    # The model even re-offers a used subject; the workflow must drop it and still return N fresh.
    _patch_agents(
        monkeypatch,
        main,
        sources=sources,
        chosen=["Old finding", "Fresh one", "Fresh two"],
    )
    ctx = _ctx(tmp_path, video_count=2)
    token = set_active(ctx)
    try:
        ctx.library.put("used-subjects", ["Old finding"], kind="value")  # seed prior run
        shared = main.prepare(ctx)
    finally:
        reset_active(token)
    subjects = shared["subjects"]
    assert "Old finding" not in subjects
    assert len(subjects) == 2 and len(set(subjects)) == 2
    # the chosen subjects were appended to the cross-run dedup list
    used_after = set(ctx.library.value("used-subjects") or [])
    assert set(subjects) <= used_after and "Old finding" in used_after


def test_prepare_empty_on_allowlist_pool_fails_cleanly(tmp_path: Path, monkeypatch) -> None:
    main = _load_main()
    # Real run: research returns only OFF-allowlist sources -> broaden still empty -> clean fail.
    off_list = [
        _src(main, "https://example.invalid/x", "off"),
        _src(main, "https://blog.test/y", "off"),
    ]
    _patch_agents(monkeypatch, main, sources=off_list, chosen=[])
    ctx = _ctx(tmp_path, video_count=1, dry_run=False)
    token = set_active(ctx)
    try:
        with pytest.raises(RuntimeError):
            main.prepare(ctx)
    finally:
        reset_active(token)
