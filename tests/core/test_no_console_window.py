"""Regression: suppress Windows console windows across the ordinary-build spawn sites.

On Windows a console child launched from a windowless parent gets its OWN visible console window
unless it is created with `CREATE_NO_WINDOW`. The video renderer already sets it
(`tests/sdk/test_graphics_no_console_window.py`, whose docstring notes builds used to "leave dozens
of orphaned console windows piled up"). The SAME storm happens during ordinary editing/builds from
sites that never got the flag: the Cursor afterFileEdit hooks (ruff, prettier) that fire on every
edit, the process-teardown `taskkill`, and the venv-setup subprocess probes. Pin the mechanism here
so those run windowless. Asserting "no OS window appeared" is not unit-testable; instead each spawn
site must pass `creationflags` including `CREATE_NO_WINDOW` on Windows (and 0 elsewhere).
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[2]
_EXPECTED = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _load_hook(name: str) -> Any:
    path = _REPO / ".cursor" / "hooks" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_hook_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _feed_stdin(monkeypatch: pytest.MonkeyPatch, module: Any, payload: dict[str, Any]) -> None:
    data = json.dumps(payload).encode("utf-8")
    monkeypatch.setattr(module.sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(data)))


def _spy_run(monkeypatch: pytest.MonkeyPatch, module: Any) -> list[Any]:
    seen: list[Any] = []

    def fake_run(args: list[str], **kwargs: Any) -> Any:
        seen.append(kwargs.get("creationflags"))
        return types.SimpleNamespace(returncode=0, stdout="python\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    return seen


def test_lint_edit_hook_spawns_ruff_windowless(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "sample.py"
    target.write_text("x = 1\n", encoding="utf-8")
    module = _load_hook("lint_edit")
    seen = _spy_run(monkeypatch, module)
    _feed_stdin(monkeypatch, module, {"file_path": str(target)})

    module.main()

    assert seen  # ruff was invoked (check + format)
    assert all(flag == _EXPECTED for flag in seen)


def test_format_frontend_hook_spawns_prettier_windowless(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frontend = tmp_path / "frontend"
    (frontend / "src").mkdir(parents=True)
    target = frontend / "src" / "Sample.tsx"
    target.write_text("export const x = 1;\n", encoding="utf-8")
    prettier = frontend / "node_modules" / "prettier" / "bin" / "prettier.cjs"
    prettier.parent.mkdir(parents=True)
    prettier.write_text("// stub\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    module = _load_hook("format_frontend")
    monkeypatch.setattr(module.shutil, "which", lambda name: "node" if name == "node" else None)
    seen = _spy_run(monkeypatch, module)
    _feed_stdin(monkeypatch, module, {"file_path": str(target)})

    module.main()

    assert seen  # prettier was invoked
    assert all(flag == _EXPECTED for flag in seen)


@pytest.mark.skipif(sys.platform != "win32", reason="taskkill path is Windows-only")
def test_kill_tree_taskkill_windowless(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import proc

    seen = _spy_run(monkeypatch, proc)
    fake_proc = types.SimpleNamespace(
        poll=lambda: None, pid=4321, wait=lambda timeout=None: 0, kill=lambda: None
    )
    proc.kill_tree(fake_proc)  # type: ignore[arg-type]

    assert seen and seen[0] == subprocess.CREATE_NO_WINDOW


def test_env_setup_runs_windowless(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import env

    seen = _spy_run(monkeypatch, env)
    env._run_timed(["python", "-c", "pass"])

    assert seen and all(flag == _EXPECTED for flag in seen)


def test_env_python_probe_runs_windowless(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import env

    monkeypatch.setattr(env.shutil, "which", lambda name: "py" if name == "py" else None)
    seen = _spy_run(monkeypatch, env)
    # returns None because the stubbed stdout path is not a real file; we only care about the spawn.
    env.default_find_python("3.12")

    assert seen and all(flag == _EXPECTED for flag in seen)
