"""Cost estimation from run history (PRD §7.3, Stage C).

Before a run, estimate its cost per meter from the last comparable runs. Match on the params a
workflow declares `affects_cost` (model, duration, shot count) — not free-text params like topic,
which differ every time. Average the **`uncached`** figure (what the work costs fresh, ignoring
cache reuse: a resumed run that reused cached steps says nothing about a fresh one). Exclude runs
that skew the average: failed / stopped / stopped-budget runs (partial pay) and dry runs (free).
The estimate states its own confidence: matched against N similar runs, a crude workflow-wide
average, or no data.

SKELETON — signatures frozen by tests/core/test_estimate.py; the builder fills the bodies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.records import RequestRecord, read_request, read_video

# Estimates are drawn from at most this many most-recent comparable runs (PRD §7.3: "last ten").
MAX_HISTORY = 10
# Only completed history feeds estimates; running/pending (and failed/stopped/dry) are excluded.
INCLUDED_STATUSES = frozenset({"complete", "partial"})


@dataclass(frozen=True)
class Estimate:
    """A per-meter cost estimate with its confidence.

    `per_meter` maps a meter id (e.g. "openrouter") to the average *uncached* amount over the runs
    the estimate is based on. `confidence` is "matched" (same affects_cost params), "crude" (a
    workflow-wide average, no param match), or "none" (no usable history). `matches` is the count of
    runs averaged.
    """

    per_meter: dict[str, float]
    confidence: str
    matches: int


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

    return Estimate(per_meter=_mean_uncached(pool), confidence=confidence, matches=len(pool))


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


def _try_read_request(run_dir: Path) -> RequestRecord | None:
    try:
        return read_request(run_dir)
    except (OSError, TypeError, ValueError):
        return None


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
    return totals
