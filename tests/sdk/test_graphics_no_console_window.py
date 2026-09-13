"""Regression: the node launch behind `check()`/`render` must not open a console window on Windows.

`sfvf.media.graphics._run` is the single place that spawns `node` (used by both the composition
`check()` and `render`). On Windows, `node` — and the `chrome-headless-shell` / FFmpeg processes it
in turn spawns — inherit a visible console window unless the process is created with
`CREATE_NO_WINDOW`. Before this fix, a full test run left dozens of orphaned `chrome-headless-shell`
console windows piled up in the terminal.

Asserting "no OS window appeared" is not unit-testable, so this pins the mechanism: `_run` must pass
`creationflags` including `CREATE_NO_WINDOW` on Windows (and 0 elsewhere, where the flag does not
exist and consoles are not an issue). A spy on `subprocess.Popen` captures the kwargs and aborts
before the real process lifecycle, so the test starts nothing.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest
from sfvf.media import graphics


def test_run_spawns_node_with_no_console_window(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_popen(command: list[str], **kwargs: Any) -> object:
        captured["creationflags"] = kwargs.get("creationflags")
        raise OSError("stop before the real process lifecycle")

    monkeypatch.setattr(graphics.subprocess, "Popen", fake_popen)

    with pytest.raises(RuntimeError):
        graphics._run(["node", "--version"])

    expected = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    assert captured["creationflags"] == expected
