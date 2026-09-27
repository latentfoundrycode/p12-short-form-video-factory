# TASK F2a-fix2 — per-video averaging + drive-relative path guard

Two frozen-test failures to fix (RED). Do NOT edit tests.

## 1. Per-video averaging (Review B blocker) — app/core/estimate.py::average_cost_per_meter
R-005 is the average cost of ONE VIDEO across the last 10 runs. Current code sums all videos in a run
and divides by the number of runs, so a 3-video run counts as 3x a 1-video run. Cost is stored per
video (§7.3/R-092) so runs stay comparable.
Fix: for each counted run, compute its PER-VIDEO cost = (sum of finished videos' cost["actual"] +
`prepare_cost["actual"]`) divided by the number of FINISHED videos (count only videos whose status is
`complete`, mirroring `_run_uncached`'s H27(b) rule). A run with zero finished videos still counts in
`runs_counted` but contributes nothing (never divide by zero). Then average those per-run per-video
figures across the pool, still dividing by POOL SIZE (keep test_meter_absent...divides_by_pool_size
green). Frozen: test_averages_per_video_not_per_request (1-video + 3-video @1.00 -> 1.00, not 2.00),
test_prepare_cost_spread_across_videos (2 videos @0.10 + prepare 0.04 -> 0.12). Keep the existing
1-video tests green.

## 2. Windows drive-relative path escape (security BLOCKING) — app/paths.py + app/api/runs.py
`is_safe_path_segment("C:")` returns True, but `runs_dir / "C:"` resets to the C: drive root on
Windows. Newly reachable via F2a's `_require_workflow_readable` (and run_id).
Fix (both layers):
- app/paths.py `is_safe_path_segment`: reject any drive/colon segment — `if ":" in name: return False`
  (also cover `Path(name).drive`). Legit workflow ids / run ids never contain ":". Frozen:
  tests/test_paths.py::test_is_safe_path_segment_rejects_windows_drive_relative.
- app/api/runs.py `_workflow_has_runs_on_disk`: after joining, assert containment as defense-in-depth
  (`root.resolve().is_relative_to(_runs_dir(request).resolve())` else False) and wrap `iterdir()` in
  try/except OSError -> return False (a directory vanishing mid-read must not 500).

## Done when
- `./.venv/Scripts/python.exe -m pytest tests/api tests/core tests/test_paths.py -q` — only the 2
  pre-existing httpx `..`-path failures remain.
- `ruff check .`, `ruff format --check .`, `mypy` clean. No test files edited.
- End with an `Assumed, not verified` list (or `none`).
