"""Spend-over-time aggregation for the Statistics tab (PRD §8.6, Architecture `/statistics`).

Walk every workflow's runs, sum the **actual** per-meter spend recorded on each video, and bucket it
by calendar month across a trailing window. Meters are grouped by kind (§7.1): all fiat meters are
summed into one series ("euros are euros"); each credit meter is its own series, never combined with
another's. Unlike cost *estimation* (which wants clean completed runs), spend statistics count every
real charge — a stopped or failed run still spent money on the videos that finished — so only *dry*
runs (which spend nothing) are excluded. Malformed amounts are skipped, not fatal (§8, the C-1/C-3
lesson: guard float() against overflow; drop non-finite and negative).

SKELETON — the `Bucket`/`Series`/`aggregate_statistics` names and signatures are frozen by
tests/core/test_statistics.py; the builder fills the bodies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.meters import METERS, MeterInfo


@dataclass(frozen=True)
class Bucket:
    """One month's summed spend for a series. `month` is "YYYY-MM"; `amount` is >= 0 and finite."""

    month: str
    amount: float


@dataclass(frozen=True)
class Series:
    """A displayable spend line.

    `id` is "fiat" for the combined fiat line, else the meter id. `kind` is "fiat" or "credit".
    `label` is the display name ("Fiat currency", or the provider for a credit line). `providers`
    lists the provider labels the line covers (one for a credit line; the sorted fiat providers that
    appear, for the fiat line). `unit` is the shared unit. `buckets` has one entry per month in the
    window, ascending, zero-filled where nothing was spent. `total` is the sum of the buckets.
    """

    id: str
    kind: str
    label: str
    providers: list[str]
    unit: str
    total: float
    buckets: list[Bucket]


def aggregate_statistics(
    runs_dir: Path,
    *,
    months: int,
    now: datetime,
    registry: dict[str, MeterInfo] = METERS,
) -> list[Series]:
    """Aggregate actual spend into per-meter monthly series over the trailing `months` window.

    The window is the `months` calendar months ending with the month of `now` (inclusive). A run is
    counted when its `started_utc` month falls in the window and it is not a dry run, regardless of
    status. Each video's `cost["actual"]` contributes its per-meter amount. Fiat meters are summed
    into a single "fiat" series; each non-fiat meter becomes its own series; a meter absent from the
    registry becomes a standalone credit series (never merged into fiat). The fiat series appears
    first (when present), then the rest sorted by label. Each series' `buckets` cover every month in
    the window in ascending order. Pure and read-only; tolerant of malformed records.
    """
    raise NotImplementedError
