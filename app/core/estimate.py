"""Cost estimation from run history (PRD §7.3, Stage C).

Before a run, estimate its cost per meter from the last comparable runs. Match on the params a
workflow declares `affects_cost` (model, duration, shot count) — not free-text params like topic,
which differ every time. Average the **`uncached`** figure (what the work costs fresh, ignoring
cache reuse: a resumed run that reused cached steps says nothing about a fresh one). Only completed
history feeds estimates — an allowlist of `complete` and `partial` runs: `partial` is
success-with-attrition, its finished work is usable, whereas running/pending (including the current
run at admission), failed/stopped/stopped-budget, and dry runs (free) are all excluded.
The estimate states its own confidence: matched against N similar runs, a crude workflow-wide
average, or no data.

SKELETON — signatures frozen by tests/core/test_estimate.py; the builder fills the bodies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core.records import RequestRecord, read_events, read_request, read_video
from app.paths import is_safe_path_segment

# Estimates are drawn from at most this many most-recent comparable runs (PRD §7.3: "last ten").
MAX_HISTORY = 10
# Only completed history feeds estimates; running/pending (and failed/stopped/dry) are excluded.
INCLUDED_STATUSES = frozenset({"complete", "partial"})


@dataclass(frozen=True)
class StageSnapshot:
    index: int
    total: int
    label: str


@dataclass(frozen=True)
class ProgressSnapshot:
    done: int
    total: int


@dataclass(frozen=True)
class LastRunSnapshot:
    run_id: str
    status: str
    stage: StageSnapshot | None
    progress: ProgressSnapshot | None


@dataclass(frozen=True)
class Estimate:
    """A per-meter cost estimate with its confidence.

    `per_meter` maps a meter id (e.g. "openrouter") to the average *uncached* amount over the runs
    the estimate is based on. `prepare_per_meter` is the per-run prepare overhead (not scaled by
    video count). `confidence` is "matched" (same affects_cost params), "crude" (a workflow-wide
    average, no param match), or "none" (no usable history). `matches` is the count of runs
    averaged.
    """

    per_meter: dict[str, float]
    confidence: str
    matches: int
    prepare_per_meter: dict[str, float] = field(default_factory=dict)


def estimate_cost(
    runs_dir: Path,
    workflow_id: str,
    params: dict[str, Any],
    affects_cost_keys: frozenset[str],
) -> Estimate:
    """Estimate per-meter uncached cost for a prospective run of `workflow_id` with `params`.

    Reads the workflow's prior runs under `runs_dir/workflow_id`, keeps only completed non-dry runs,
    prefers those whose `affects_cost_keys` param values equal `params`, and averages their
    per-meter uncached cost over the most recent `MAX_HISTORY`. Falls back to a crude workflow-wide
    average, then to no data. Pure and read-only.
    """
    candidates = _candidates(runs_dir, workflow_id)
    if not candidates:
        return Estimate(per_meter={}, confidence="none", matches=0)

    matched = [
        item
        for item in candidates
        if all(item[1].params.get(key) == params.get(key) for key in affects_cost_keys)
    ]
    if matched:
        pool = matched[:MAX_HISTORY]
        confidence = "matched"
    else:
        pool = candidates[:MAX_HISTORY]
        confidence = "crude"

    return Estimate(
        per_meter=_mean_uncached(pool),
        confidence=confidence,
        matches=len(pool),
        prepare_per_meter=_mean_prepare(pool),
    )


def average_cost_per_meter(
    runs_dir: Path, workflow_id: str, *, limit: int = 10
) -> tuple[dict[str, float], int]:
    """Mean actual cost per meter across the workflow's most recent counted runs (PRD §8.1).

    Uses the same candidate pool as cost estimates (`complete`/`partial`, non-dry). For each run,
    per-video actual cost (finished videos' `cost["actual"]` plus `prepare_cost["actual"]`, divided
    by the count of videos with status `complete`) is averaged over the pool size.
    """
    pool = _candidates(runs_dir, workflow_id)[:limit]
    if not pool:
        return ({}, 0)
    pool_size = len(pool)
    sums: dict[str, float] = {}
    for run_dir, record in pool:
        for meter, amount in _run_per_video_actual_with_prepare(run_dir, record).items():
            total = sums.get(meter, 0.0) + amount
            if not math.isfinite(total):
                continue
            sums[meter] = total
    result: dict[str, float] = {}
    for meter, total in sums.items():
        mean = total / pool_size
        if math.isfinite(mean):
            result[meter] = mean
    return (result, pool_size)


def last_run_snapshot(runs_dir: Path, workflow_id: str) -> LastRunSnapshot | None:
    """Newest run dir (by run-id name) for card state: status plus last stage/progress events."""
    root = runs_dir / workflow_id
    if not root.is_dir():
        return None
    try:
        children = list(root.iterdir())
    except OSError:
        return None
    run_dirs = [
        child for child in children if child.is_dir() and (child / "request.json").is_file()
    ]
    if not run_dirs:
        return None
    run_dirs.sort(key=lambda path: path.name, reverse=True)
    run_dir = run_dirs[0]
    record = _try_read_request(run_dir)
    if record is None:
        return None
    stage: StageSnapshot | None = None
    progress: ProgressSnapshot | None = None
    try:
        for _ts, _source, event in read_events(run_dir):
            if not isinstance(event, dict):
                continue
            kind = event.get("t")
            if kind == "stage":
                maybe_stage = _parse_stage_event(event)
                if maybe_stage is not None:
                    stage = maybe_stage
            elif kind == "progress":
                maybe_progress = _parse_progress_event(event)
                if maybe_progress is not None:
                    progress = maybe_progress
    except OSError:
        pass
    return LastRunSnapshot(
        run_id=run_dir.name,
        status=record.status,
        stage=stage,
        progress=progress,
    )


def archived_workflow_ids(runs_dir: Path, known_ids: set[str]) -> list[str]:
    """Workflow folder names under `runs_dir` that have run output but no live plugin folder."""
    if not runs_dir.is_dir():
        return []
    try:
        children = list(runs_dir.iterdir())
    except OSError:
        return []
    found: list[str] = []
    for child in children:
        if not child.is_dir():
            continue
        name = child.name
        if not is_safe_path_segment(name) or name in known_ids:
            continue
        if _has_request_json_run(child):
            found.append(name)
    return sorted(found)


def scale_estimate(estimate: Estimate, count: int) -> Estimate:
    """Scale a PER-VIDEO estimate to a whole run of `count` videos, then add the per-run prepare
    overhead once. Confidence and matches are preserved; `prepare_per_meter` is folded into
    `per_meter` so scaling twice never double-adds."""
    meters = estimate.per_meter.keys() | estimate.prepare_per_meter.keys()
    return Estimate(
        per_meter={
            meter: estimate.per_meter.get(meter, 0.0) * count
            + estimate.prepare_per_meter.get(meter, 0.0)
            for meter in meters
        },
        confidence=estimate.confidence,
        matches=estimate.matches,
        prepare_per_meter={},
    )


def _candidates(runs_dir: Path, workflow_id: str) -> list[tuple[Path, RequestRecord]]:
    root = runs_dir / workflow_id
    if not root.is_dir():
        return []
    try:
        children = list(root.iterdir())
    except OSError:
        return []
    found: list[tuple[Path, RequestRecord]] = []
    for child in children:
        if not child.is_dir():
            continue
        record = _try_read_request(child)
        if record is None:
            continue
        if record.status not in INCLUDED_STATUSES or record.dry_run:
            continue
        found.append((child, record))
    found.sort(key=lambda item: item[0].name, reverse=True)
    return found


def _has_request_json_run(workflow_runs_root: Path) -> bool:
    try:
        children = list(workflow_runs_root.iterdir())
    except OSError:
        return False
    return any(child.is_dir() and (child / "request.json").is_file() for child in children)


def _run_per_video_actual_with_prepare(run_dir: Path, record: RequestRecord) -> dict[str, float]:
    """Per-video actual for one run: complete videos' actual plus prepare, divided by N complete."""
    video_sums: dict[str, float] = {}
    complete = 0
    try:
        children = list(run_dir.iterdir())
    except OSError:
        return {}
    for child in children:
        if not child.is_dir() or not (child / "video.json").is_file():
            continue
        try:
            video = read_video(child)
        except (OSError, TypeError, ValueError):
            continue
        if video.status != "complete":
            continue
        complete += 1
        cost = video.cost
        if not isinstance(cost, dict):
            continue
        actual = cost.get("actual")
        if not isinstance(actual, dict):
            continue
        for meter, raw in actual.items():
            if isinstance(raw, bool) or not isinstance(raw, int | float):
                continue
            try:
                amount = float(raw)
            except (OverflowError, ValueError):
                continue
            if not math.isfinite(amount) or amount < 0.0:
                continue
            running = video_sums.get(meter, 0.0) + amount
            if not math.isfinite(running):
                continue
            video_sums[meter] = running
    if complete == 0:
        return {}
    prepare_sums: dict[str, float] = {}
    prepare = record.prepare_cost
    if isinstance(prepare, dict):
        prepare_actual = prepare.get("actual")
        if isinstance(prepare_actual, dict):
            for meter, raw in prepare_actual.items():
                if isinstance(raw, bool) or not isinstance(raw, int | float):
                    continue
                try:
                    amount = float(raw)
                except (OverflowError, ValueError):
                    continue
                if not math.isfinite(amount) or amount < 0.0:
                    continue
                prepare_sums[meter] = amount
    divisor = Decimal(complete)
    meters = video_sums.keys() | prepare_sums.keys()
    result: dict[str, float] = {}
    for meter in meters:
        meter_total = Decimal(str(video_sums.get(meter, 0.0))) + Decimal(
            str(prepare_sums.get(meter, 0.0))
        )
        mean = float(meter_total / divisor)
        if math.isfinite(mean):
            result[meter] = mean
    return result


def _parse_stage_event(event: dict[str, Any]) -> StageSnapshot | None:
    index = event.get("index")
    total = event.get("total")
    label = event.get("label")
    if not isinstance(index, int) or not isinstance(total, int) or not isinstance(label, str):
        return None
    return StageSnapshot(index=index, total=total, label=label)


def _parse_progress_event(event: dict[str, Any]) -> ProgressSnapshot | None:
    done = event.get("done")
    total = event.get("total")
    if not isinstance(done, int) or not isinstance(total, int):
        return None
    return ProgressSnapshot(done=done, total=total)


def _try_read_request(run_dir: Path) -> RequestRecord | None:
    try:
        return read_request(run_dir)
    except (OSError, TypeError, ValueError):
        return None


def _mean_prepare(pool: list[tuple[Path, RequestRecord]]) -> dict[str, float]:
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for _run_dir, record in pool:
        prepare = record.prepare_cost
        if not isinstance(prepare, dict):
            continue
        uncached = prepare.get("uncached")
        if not isinstance(uncached, dict):
            continue
        for meter, raw in uncached.items():
            if isinstance(raw, bool) or not isinstance(raw, int | float):
                continue
            try:
                amount = float(raw)
            except (OverflowError, ValueError):
                continue
            if not math.isfinite(amount) or amount < 0.0:
                continue
            total = sums.get(meter, 0.0) + amount
            if not math.isfinite(total):
                continue
            sums[meter] = total
            counts[meter] = counts.get(meter, 0) + 1
    result: dict[str, float] = {}
    for meter in sums:
        mean = sums[meter] / counts[meter]
        if math.isfinite(mean):
            result[meter] = mean
    return result


def _mean_uncached(pool: list[tuple[Path, RequestRecord]]) -> dict[str, float]:
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for run_dir, _record in pool:
        for meter, amount in _run_uncached(run_dir).items():
            sums[meter] = sums.get(meter, 0.0) + amount
            counts[meter] = counts.get(meter, 0) + 1
    result: dict[str, float] = {}
    for meter in sums:
        mean = sums[meter] / counts[meter]
        if math.isfinite(mean):
            result[meter] = mean
    return result


def _run_uncached(run_dir: Path) -> dict[str, float]:
    totals: dict[str, float] = {}
    complete = 0
    try:
        children = list(run_dir.iterdir())
    except OSError:
        return totals
    for child in children:
        if not child.is_dir() or not (child / "video.json").is_file():
            continue
        try:
            video = read_video(child)
        except (OSError, TypeError, ValueError):
            continue
        if video.status != "complete":
            continue  # H27(b): non-complete videos' cost must not leak into the per-video unit
        complete += 1
        cost = video.cost
        if not isinstance(cost, dict):
            continue
        uncached = cost.get("uncached")
        if not isinstance(uncached, dict):
            continue
        for meter, raw in uncached.items():
            if isinstance(raw, bool) or not isinstance(raw, int | float):
                continue
            try:
                amount = float(raw)
            except (OverflowError, ValueError):
                continue
            if not math.isfinite(amount) or amount < 0.0:
                continue
            total = totals.get(meter, 0.0) + amount
            if not math.isfinite(total):
                continue
            totals[meter] = total
    if complete == 0:
        return {}
    return {meter: total / complete for meter, total in totals.items()}
