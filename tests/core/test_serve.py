"""PKG-1 contract: the `sfvf` launch command (Delivery §3 launcher + §4 command reference).

SFVF is launched today only by a raw `uvicorn app.main:app` line. The installer needs a first-party
command to put on PATH: `sfvf` starts the server on 127.0.0.1:8000 and opens the browser; `sfvf
--version` prints the version; `sfvf --no-browser`/`--host`/`--port` adjust it. Because
this is SFVF's first command-line surface, §4 also requires a machine-readable
`docs/cli-reference.json` generated from the real parser (kept current by a CI check), so no
run-sheet or manual ever names a command that does not exist.

`app.serve` exposes `main(argv) -> int`, `read_version() -> str`, and `cli_reference() -> dict`. Two
seams — `_run_uvicorn(host, port)` and `_open_browser(url)` — are patched so the test drives the
wiring without binding a socket or opening a real browser. No network, no spend.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import serve
from app.paths import APP_ROOT


def test_read_version_is_the_single_source(tmp_path: Path) -> None:
    file_version = (APP_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert file_version  # the single source exists and is non-empty
    assert serve.read_version() == file_version


def test_main_version_prints_the_version_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert serve.main(["--version"]) == 0
    assert serve.read_version() in capsys.readouterr().out


def test_main_help_exits_zero() -> None:
    # argparse --help exits 0 (SystemExit) — a launcher's help must not look like a failure.
    with pytest.raises(SystemExit) as exc:
        serve.main(["--help"])
    assert exc.value.code == 0


def _patch_seams(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    seen: dict[str, object] = {"uvicorn": None, "browser": None}

    def fake_run(host: str, port: int) -> None:
        seen["uvicorn"] = (host, port)

    def fake_open(url: str) -> None:
        seen["browser"] = url

    monkeypatch.setattr(serve, "_run_uvicorn", fake_run)
    monkeypatch.setattr(serve, "_open_browser", fake_open)
    return seen


def test_default_serves_localhost_8000_and_opens_the_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _patch_seams(monkeypatch)
    assert serve.main([]) == 0
    assert seen["uvicorn"] == ("127.0.0.1", 8000)
    assert seen["browser"] == "http://127.0.0.1:8000"


def test_no_browser_flag_suppresses_the_browser_but_still_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _patch_seams(monkeypatch)
    assert serve.main(["--no-browser"]) == 0
    assert seen["uvicorn"] == ("127.0.0.1", 8000)
    assert seen["browser"] is None  # browser never opened


def test_host_and_port_flow_to_uvicorn_and_the_browser_url(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _patch_seams(monkeypatch)
    assert serve.main(["--host", "127.0.0.9", "--port", "9000"]) == 0
    assert seen["uvicorn"] == ("127.0.0.9", 9000)
    assert seen["browser"] == "http://127.0.0.9:9000"


def test_cli_reference_is_current(tmp_path: Path) -> None:
    # §4: the committed reference is generated from the real parser, so `cli_reference()` must equal
    # the committed docs/cli-reference.json (the CI currency check enforces the same equality).
    committed = json.loads((APP_ROOT / "docs" / "cli-reference.json").read_text(encoding="utf-8"))
    assert serve.cli_reference() == committed


def test_cli_reference_describes_the_sfvf_command() -> None:
    ref = serve.cli_reference()
    # The reference names the command and its version and the flags a manual/run-sheet would cite.
    dumped = json.dumps(ref)
    assert "sfvf" in dumped
    assert "--no-browser" in dumped
    assert "--port" in dumped
