"""TASK-SSN-A8 contract: the supervisor wires the owner-pool root into every run context.

A4 added `ContextPaths.library_owner_pool` and the `ctx.library` facade reads/grant-filters it, but
nothing populated that field on a real run, so `paths.library_owner_pool` was always None and the
whole owner-pool grant path (A2 GrantStore + A4 facade) was dead code at runtime. This pins the
missing wiring: a real run's context.json must carry `paths.library_owner_pool` set to
`<library_dir>/_owner` -- the SAME root the app's Library-tab endpoints write to
(`app/api/library.py::_owner_root`) -- so a granted owner soundtrack/voice asset is reachable by
`ctx.library.path` at run time.

Supervisor-authored frozen contract (RED-first); the builder implements app/core/supervisor.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.core.env import EnvBlocked, EnvReady
from app.core.supervisor import RunBusy, run_request

STUBS = Path(__file__).resolve().parent.parent / "stubs"


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def test_real_run_context_carries_owner_pool_root(tmp_path: Path) -> None:
    library_dir = tmp_path / "library"
    result = run_request(
        STUBS / "succeeds",
        params={"topic": "test"},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        library_dir=library_dir,
        ensure_env=_ready,
    )
    assert not isinstance(result, EnvBlocked | RunBusy)
    run_dir = next((tmp_path / "runs" / "succeeds").iterdir())
    context = json.loads((run_dir / "01" / "context.json").read_text(encoding="utf-8"))
    assert context["paths"]["library_owner_pool"] is not None
    assert Path(context["paths"]["library_owner_pool"]) == (library_dir / "_owner").resolve()
