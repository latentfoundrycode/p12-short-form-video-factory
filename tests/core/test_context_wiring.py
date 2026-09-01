"""SDK-4 contract: the supervisor wires identity + cache into context.json, the SDK
exposes the §4.1 accessors + ctx.decision, step results cache across separate runs, and
the dry-run and real caches are isolated so fake assets never leak into a paid run.

Drives the real supervisor (subprocess-per-video, real SDK runner) against the `caching`
stub, which reads every identity accessor, records a decision, and runs one cached step.
"""

import json
import sys
from pathlib import Path

from app.core.env import EnvBlocked, EnvReady
from app.core.records import read_events, read_request
from app.core.supervisor import RunBusy, run_request

STUBS = Path(__file__).resolve().parent.parent / "stubs"
CACHING = STUBS / "caching"


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def _launch(runs_dir: Path, cache_dir: Path, *, dry_run: bool = True) -> str:
    seen: list[str] = []
    result = run_request(
        CACHING,
        params={"topic": "t"},
        video_count=2,
        concurrency=1,
        runs_dir=runs_dir,
        cache_dir=cache_dir,
        ensure_env=_ready,
        dry_run=dry_run,
        step_concurrency=3,
        on_started=seen.append,
    )
    assert not isinstance(result, EnvBlocked | RunBusy)
    assert len(seen) == 1
    return seen[0]


def _events_by_source(run_dir: Path) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for _ts, source, event in read_events(run_dir):
        grouped.setdefault(source, []).append(event)
    return grouped


def _first(events: list[dict[str, object]], kind: str) -> dict[str, object]:
    for event in events:
        if event.get("t") == kind:
            return event
    raise AssertionError(f"no {kind!r} event found")


def _body_ran(events: list[dict[str, object]]) -> bool:
    return any(e.get("t") == "log" and e.get("msg") == "computing-body" for e in events)


def test_context_wiring_identity_decision_and_cross_run_cache(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    cache_dir = tmp_path / "cache"

    # --- First run (dry): cold cache, every step body executes. ---
    run1_id = _launch(runs_dir, cache_dir)
    run1 = runs_dir / "caching" / run1_id
    assert read_request(run1).status == "complete"

    grouped1 = _events_by_source(run1)
    assert set(grouped1) == {"01", "02"}
    for source, events in grouped1.items():
        identity = _first(events, "identity")
        assert identity["workflow_id"] == "caching"
        assert identity["workflow_version"] == "1.0.0"
        assert identity["run_id"] == run1_id
        assert identity["video_index"] == int(source)
        assert identity["video_count"] == 2
        assert identity["dry_run"] is True
        assert identity["step_concurrency"] == 3
        assert identity["video_dir"] == str((run1 / source).resolve())
        assert identity["shared_dir"] == str((run1 / "shared").resolve())
        assert identity["workflow_dir"] == str(CACHING.resolve())

        decision = _first(events, "decision")
        assert decision["kind"] == "model"
        assert decision["chosen"] == "alpha"
        assert decision["alternatives"] == ["beta"]
        assert decision["reason"] == "unit test"

        step = _first(events, "step")
        assert step["name"] == "compute"
        assert step["status"] == "ok"
        assert _body_ran(events), f"step body should run on the cold cache for {source}"

    # context.json on disk carries the wired identity + the mode-partitioned cache root.
    ctx = json.loads((run1 / "01" / "context.json").read_text(encoding="utf-8"))
    assert ctx["workflow_version"] == "1.0.0"
    assert ctx["workflow_id"] == "caching"
    assert ctx["run_id"] == run1_id
    assert ctx["video_index"] == 1
    assert ctx["video_count"] == 2
    assert ctx["dry_run"] is True
    assert ctx["step_concurrency"] == 3
    assert Path(ctx["paths"]["cache"]) == (cache_dir / "caching" / "dry").resolve()
    assert Path(ctx["paths"]["workflow"]) == CACHING.resolve()

    # --- Second run (dry): warm cache (same dry partition), step bodies are skipped. ---
    run2_id = _launch(runs_dir, cache_dir)
    assert run2_id != run1_id
    run2 = runs_dir / "caching" / run2_id
    assert read_request(run2).status == "complete"

    grouped2 = _events_by_source(run2)
    assert set(grouped2) == {"01", "02"}
    for source, events in grouped2.items():
        identity = _first(events, "identity")
        assert identity["run_id"] == run2_id
        assert identity["video_index"] == int(source)

        step = _first(events, "step")
        assert step["name"] == "compute"
        assert step["status"] == "cached"
        assert not _body_ran(events), f"warm dry cache should skip the body for {source}"

    # --- Third run (real): the dry cache must NOT poison a real run. Same inputs, but a
    # real run reads a separate partition, so every step body must execute again. ---
    run3_id = _launch(runs_dir, cache_dir, dry_run=False)
    run3 = runs_dir / "caching" / run3_id
    assert read_request(run3).status == "complete"

    ctx_real = json.loads((run3 / "01" / "context.json").read_text(encoding="utf-8"))
    assert ctx_real["dry_run"] is False
    assert Path(ctx_real["paths"]["cache"]) == (cache_dir / "caching" / "real").resolve()

    grouped3 = _events_by_source(run3)
    assert set(grouped3) == {"01", "02"}
    for source, events in grouped3.items():
        identity = _first(events, "identity")
        assert identity["dry_run"] is False
        step = _first(events, "step")
        assert step["name"] == "compute"
        assert step["status"] == "ok", f"real run must not reuse the dry cache for {source}"
        assert _body_ran(events), f"real body must execute, not reuse dry cache, for {source}"
