"""D-3c contract: the supervisor wires `ctx.library` into every run (§5.10, §7).

A real run's library writes land under `library/<namespace>` (the manifest namespace, defaulting to
the workflow id) with the declared facets validated; a dry run's writes go to a per-run overlay that
is discarded at the end, so the real library is never touched. The `library_user` stub calls
`ctx.library.put`, which only works when the supervisor has populated the context's library paths.
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


def _run(tmp_path: Path, *, dry_run: bool = False) -> object:
    return run_request(
        STUBS / "library_user",
        params={},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,
        cache_dir=tmp_path / "cache",
        library_dir=tmp_path / "lib",
        dry_run=dry_run,
    )


def _run_dir(tmp_path: Path) -> Path:
    root = tmp_path / "runs" / "library-user"
    dirs = [d for d in root.iterdir() if d.is_dir()]
    assert len(dirs) == 1
    return dirs[0]


def test_real_run_writes_to_the_declared_namespace(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert not isinstance(result, EnvBlocked | RunBusy)
    assert read_request(_run_dir(tmp_path)).status == "complete"
    # The asset is under library/<namespace> = "cast" (not the workflow id), with facets validated.
    library = LibraryStore(tmp_path / "lib" / "cast")
    asset = library.get("char/bertie")
    assert asset is not None
    assert asset.kind == "image"
    assert asset.facets == {"subject": "bertie"}
    assert library.blob_path(asset.id).read_bytes() == b"BERTIE-PIXELS"


def test_dry_run_does_not_touch_the_real_library(tmp_path: Path) -> None:
    result = _run(tmp_path, dry_run=True)
    assert not isinstance(result, EnvBlocked | RunBusy)
    assert read_request(_run_dir(tmp_path)).status == "complete"
    # The write went to the discarded overlay, not the real library.
    assert LibraryStore(tmp_path / "lib" / "cast").get("char/bertie") is None
    # And the overlay is not left behind under the run's video dir (§7.9).
    assert list((tmp_path / "runs").glob("**/.library-overlay")) == []
