import json
import subprocess
import sys
import threading
from pathlib import Path

from app.core.events import to_event

STUBS = Path(__file__).resolve().parent.parent / "stubs"


def _context_payload(tmp_path: Path) -> dict[str, object]:
    video = tmp_path / "01"
    return {
        "settings": {"topic": "test"},
        "paths": {
            "video": str(video),
            "artifacts": str(video / "artifacts"),
            "steps": str(video / ".steps"),
            "shared": str(tmp_path / "shared"),
        },
        "instructions": [],
        "secrets": {},
        "previous": None,
        "shared": None,
    }


def _write_context(tmp_path: Path) -> Path:
    path = tmp_path / "context.json"
    path.write_text(json.dumps(_context_payload(tmp_path)), encoding="utf-8")
    return path


def _run_runner(
    workflow: Path,
    context: Path,
    *,
    extra: list[str] | None = None,
    timeout: float = 10,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "sfvf.runner",
        "--workflow",
        str(workflow),
        "--context",
        str(context),
    ]
    if extra:
        command.extend(extra)
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _events(stdout: str) -> list[dict[str, object]]:
    return [to_event(line) for line in stdout.splitlines() if line]


def test_emits_stub_streams_stage_log_heartbeat_and_mutable_totals(tmp_path: Path) -> None:
    result = _run_runner(STUBS / "emits", _write_context(tmp_path))
    assert result.returncode == 0
    events = _events(result.stdout)
    assert events[0] == {"t": "stage", "index": 1, "total": 2, "label": "start"}
    assert events[1] == {"t": "log", "level": "info", "msg": "hello"}
    assert events[2] == {"t": "heartbeat", "name": "work", "waiting_on": "test"}
    assert events[3] == {"t": "stage", "index": 2, "total": 9, "label": "counted later"}
    assert events[0]["total"] != events[3]["total"]


def test_noisy_stub_non_json_becomes_log(tmp_path: Path) -> None:
    result = _run_runner(STUBS / "noisy", _write_context(tmp_path))
    assert result.returncode == 0
    events = _events(result.stdout)
    assert events[0] == {"t": "log", "level": "info", "msg": "progress bar |||||"}
    assert events[1] == {"t": "log", "level": "info", "msg": "after noise"}


def test_hang_stub_flushes_then_is_terminated(tmp_path: Path) -> None:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "sfvf.runner",
            "--workflow",
            str(STUBS / "hang"),
            "--context",
            str(_write_context(tmp_path)),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    lines: list[str] = []
    ready = threading.Event()

    def _read() -> None:
        assert proc.stdout is not None
        lines.append(proc.stdout.readline())
        ready.set()

    try:
        threading.Thread(target=_read, daemon=True).start()
        assert ready.wait(timeout=5)
        event = to_event(lines[0].rstrip("\n"))
        assert event == {"t": "log", "level": "info", "msg": "before hang"}
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_unsafe_entrypoint_exits_nonzero_with_error_log(tmp_path: Path) -> None:
    result = _run_runner(STUBS / "unsafe_entry", _write_context(tmp_path))
    assert result.returncode != 0
    events = _events(result.stdout)
    assert events
    assert events[-1]["t"] == "log"
    assert events[-1]["level"] == "error"


def test_missing_entrypoint_exits_nonzero_with_error_log(tmp_path: Path) -> None:
    result = _run_runner(STUBS / "missing_entry", _write_context(tmp_path))
    assert result.returncode != 0
    events = _events(result.stdout)
    assert events
    assert events[-1]["t"] == "log"
    assert events[-1]["level"] == "error"


def test_bad_context_json_exits_nonzero_with_error_log(tmp_path: Path) -> None:
    context = tmp_path / "context.json"
    context.write_text('{"settings": {}, "unexpected": true}', encoding="utf-8")
    result = _run_runner(STUBS / "emits", context)
    assert result.returncode != 0
    events = _events(result.stdout)
    assert events
    assert events[-1]["t"] == "log"
    assert events[-1]["level"] == "error"


def test_prepare_entry_without_prepare_errors(tmp_path: Path) -> None:
    result = _run_runner(STUBS / "succeeds", _write_context(tmp_path), extra=["--entry", "prepare"])
    assert result.returncode != 0
    events = _events(result.stdout)
    assert events
    assert events[-1]["t"] == "log"
    assert events[-1]["level"] == "error"


def test_prepare_entry_writes_result_dict(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result = _run_runner(
        STUBS / "prepares",
        _write_context(tmp_path),
        extra=["--entry", "prepare", "--result", str(result_path)],
    )
    assert result.returncode == 0
    assert json.loads(result_path.read_text(encoding="utf-8")) == {"script": "hello from prep"}
    events = _events(result.stdout)
    assert {"t": "log", "level": "info", "msg": "prep-ok"} in events


def test_prepare_none_writes_result_null(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result = _run_runner(
        STUBS / "prepare_none",
        _write_context(tmp_path),
        extra=["--entry", "prepare", "--result", str(result_path)],
    )
    assert result.returncode == 0
    assert json.loads(result_path.read_text(encoding="utf-8")) is None


def test_prepare_non_dict_return_is_error(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result = _run_runner(
        STUBS / "prepare_bad_return",
        _write_context(tmp_path),
        extra=["--entry", "prepare", "--result", str(result_path)],
    )
    assert result.returncode != 0
    assert not result_path.exists()
    events = _events(result.stdout)
    assert events
    assert events[-1]["level"] == "error"
