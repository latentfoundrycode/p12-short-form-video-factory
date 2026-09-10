"""D-3c review hardening: overlay sharing + dry-run isolation edges the review surfaced.

1. The dry-run overlay is one per RUN, shared by prepare() and every video — so an asset from
   prepare() (the documented place, §7.5) is visible to run(), and the overlay is discarded whole.
2. A dry run must not create real-library state (no `library/<namespace>` dir).
"""

from __future__ import annotations

import sys
from pathlib import Path

from sfvf.library import LibraryStore

from app.core.env import EnvBlocked, EnvReady
from app.core.records import read_request
from app.core.supervisor import RunBusy, run_request

STUBS = Path(__file__).resolve().parent.parent / "stubs"


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def _run(tmp_path: Path, workflow: str, *, dry_run: bool) -> object:
    return run_request(
        STUBS / workflow,
        params={},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,
        cache_dir=tmp_path / "cache",
        library_dir=tmp_path / "lib",
        dry_run=dry_run,
    )


def _run_dir(tmp_path: Path, workflow_id: str) -> Path:
    dirs = [d for d in (tmp_path / "runs" / workflow_id).iterdir() if d.is_dir()]
    assert len(dirs) == 1
    return dirs[0]


def test_dry_run_prepare_asset_is_visible_to_run_and_overlay_discarded(tmp_path: Path) -> None:
    result = _run(tmp_path, "library_prepare", dry_run=True)
    assert not isinstance(result, EnvBlocked | RunBusy)
    # run() asserts it can see the prepare-provisioned asset; a complete status proves the shared
    # overlay worked (a per-video overlay would have made run() raise → failed).
    assert read_request(_run_dir(tmp_path, "library-prepare")).status == "complete"
    # The real library is untouched, and no overlay is left behind anywhere under runs/.
    assert LibraryStore(tmp_path / "lib" / "cast").get("char/hero") is None
    assert list((tmp_path / "runs").glob("**/.library-overlay")) == []


def test_dry_run_does_not_create_the_real_library_namespace(tmp_path: Path) -> None:
    _run(tmp_path, "library_user", dry_run=True)
    # No real-library state is created by a rehearsal — the namespace dir must not exist.
    assert not (tmp_path / "lib" / "cast").exists()


def test_real_run_prepare_asset_reaches_the_real_library(tmp_path: Path) -> None:
    result = _run(tmp_path, "library_prepare", dry_run=False)
    assert not isinstance(result, EnvBlocked | RunBusy)
    assert read_request(_run_dir(tmp_path, "library-prepare")).status == "complete"
    assert LibraryStore(tmp_path / "lib" / "cast").get("char/hero") is not None
