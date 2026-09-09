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

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.meters import METERS, MeterInfo, meter_info
from app.core.records import RequestRecord, read_request, read_video


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
    window = _month_window(now, months)
    window_set = set(window)
    totals: dict[tuple[str, str], float] = {}
    fiat_meters: set[str] = set()
    other_meters: set[str] = set()

    for run_dir in _iter_run_dirs(runs_dir):
        record = _try_read_request(run_dir)
        if record is None or record.dry_run:
            continue
        month = _month_key(record.started_utc)
        if month is None or month not in window_set:
            continue
        for meter, amount in _run_actual(run_dir).items():
            info = meter_info(meter, registry)
            series_id = "fiat" if info.kind == "fiat" else meter
            key = (series_id, month)
            total = totals.get(key, 0.0) + amount
            if not math.isfinite(total):
                continue
            totals[key] = total
            if info.kind == "fiat":
                fiat_meters.add(meter)
            else:
                other_meters.add(meter)

    series: list[Series] = []
    if fiat_meters:
        first = sorted(fiat_meters)[0]
        series.append(
            _build_series(
                series_id="fiat",
                kind="fiat",
                label="Fiat currency",
                providers=sorted({meter_info(m, registry).provider for m in fiat_meters}),
                unit=meter_info(first, registry).unit,
                window=window,
                totals=totals,
            )
        )
    credit: list[Series] = []
    for meter in other_meters:
        info = meter_info(meter, registry)
        credit.append(
            _build_series(
                series_id=meter,
                kind=info.kind,
                label=info.provider,
                providers=[info.provider],
                unit=info.unit,
                window=window,
                totals=totals,
            )
        )
    credit.sort(key=lambda item: item.label)
    series.extend(credit)
    return series


def _month_window(now: datetime, months: int) -> list[str]:
    year = now.year
    month = now.month
    keys: list[str] = []
    for _ in range(months):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    keys.reverse()
    return keys


def _month_key(started_utc: str) -> str | None:
    try:
        parsed = datetime.strptime(started_utc[:7], "%Y-%m")
    except ValueError:
        return None
    return f"{parsed.year:04d}-{parsed.month:02d}"


def _try_read_request(run_dir: Path) -> RequestRecord | None:
    try:
        return read_request(run_dir)
    except (OSError, TypeError, ValueError):
        return None


def _iter_run_dirs(runs_dir: Path) -> list[Path]:
    if not runs_dir.is_dir():
        return []
    try:
        workflows = list(runs_dir.iterdir())
    except OSError:
        return []
    found: list[Path] = []
    for workflow_dir in workflows:
        if not workflow_dir.is_dir():
            continue
        try:
            children = list(workflow_dir.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                found.append(child)
    return found


def _run_actual(run_dir: Path) -> dict[str, float]:
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
            total = totals.get(meter, 0.0) + amount
            if not math.isfinite(total):
                continue
            totals[meter] = total
    return totals


def _build_series(
    *,
    series_id: str,
    kind: str,
    label: str,
    providers: list[str],
    unit: str,
    window: list[str],
    totals: dict[tuple[str, str], float],
) -> Series:
    buckets = [Bucket(month=month, amount=totals.get((series_id, month), 0.0)) for month in window]
    return Series(
        id=series_id,
        kind=kind,
        label=label,
        providers=providers,
        unit=unit,
        total=sum(bucket.amount for bucket in buckets),
        buckets=buckets,
    )
