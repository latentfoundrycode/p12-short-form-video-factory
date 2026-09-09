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

from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Estimates are drawn from at most this many most-recent comparable runs (PRD §7.3: "last ten").
MAX_HISTORY = 10
# Runs in these terminal states paid for only part of the work, so they must not feed estimates.
EXCLUDED_STATUSES = frozenset({"failed", "stopped", "stopped-budget"})


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

    Reads the workflow's prior runs under `runs_dir/workflow_id`, drops excluded and dry runs,
    prefers those whose `affects_cost_keys` param values equal `params`, and averages their
    per-meter uncached cost over the most recent `MAX_HISTORY`. Falls back to a crude workflow-wide
    average, then to no data. Pure and read-only.
    """
    raise NotImplementedError
