from datetime import UTC, datetime
from pathlib import Path
from string import ascii_uppercase

from app.paths import RUNS_DIR, is_safe_path_segment


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_run_id(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y%m%d-%H%M%S")


def format_utc_z(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def allocate_run(workflow_id: str, *, runs_dir: Path | None = None) -> tuple[str, Path]:
    if not is_safe_path_segment(workflow_id):
        raise ValueError(f"unsafe workflow id: {workflow_id!r}")
    root = (runs_dir or RUNS_DIR) / workflow_id
    root.mkdir(parents=True, exist_ok=True)
    base = format_run_id(utc_now())
    candidates = [base, *[f"{base}{letter}" for letter in ascii_uppercase]]
    for run_id in candidates:
        if not is_safe_path_segment(run_id):
            raise ValueError(f"unsafe run id: {run_id!r}")
        path = root / run_id
        try:
            path.mkdir()
        except FileExistsError:
            continue
        return run_id, path
    raise RuntimeError(f"exhausted run-id suffixes for {base} in one UTC second")
