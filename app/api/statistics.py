"""Statistics API — spend over time, per meter (PRD §8.6, Architecture `/statistics`).

SKELETON — response shape frozen by tests/api/test_statistics.py; the builder fills the body.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.core.ids import utc_now
from app.core.statistics import aggregate_statistics
from app.paths import RUNS_DIR

router = APIRouter(prefix="/api")

# The default and maximum trailing window, in calendar months. The mockup default view is 6 months.
DEFAULT_MONTHS = 6
MAX_MONTHS = 36


class BucketOut(BaseModel):
    month: str
    amount: float


class SeriesOut(BaseModel):
    id: str
    kind: str
    label: str
    providers: list[str]
    unit: str
    total: float
    buckets: list[BucketOut]


class StatisticsOut(BaseModel):
    months: int
    series: list[SeriesOut]


def _runs_dir(request: Request) -> Path:
    return cast(Path, getattr(request.app.state, "runs_dir", RUNS_DIR))


@router.get("/statistics", response_model=StatisticsOut)
def get_statistics(
    request: Request,
    months: int = Query(default=DEFAULT_MONTHS),
) -> StatisticsOut:
    """Return per-meter monthly spend series over the trailing `months` window (clamped 1..MAX).

    Delegates to `aggregate_statistics` with the app's runs dir and the current UTC time.
    """
    clamped = min(MAX_MONTHS, max(1, months))
    series = aggregate_statistics(_runs_dir(request), months=clamped, now=utc_now())
    return StatisticsOut(
        months=clamped,
        series=[
            SeriesOut(
                id=item.id,
                kind=item.kind,
                label=item.label,
                providers=item.providers,
                unit=item.unit,
                total=item.total,
                buckets=[
                    BucketOut(month=bucket.month, amount=bucket.amount) for bucket in item.buckets
                ],
            )
            for item in series
        ],
    )
