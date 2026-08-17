import json
import sys
import threading
from pathlib import Path

from app.core.env import EnvBlocked, EnvReady
from app.core.records import read_events, read_request, read_video
from app.core.supervisor import RunBusy, run_request

STUBS = Path(__file__).resolve().parent.parent / "stubs"


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def _run(workflow: Path, tmp_path: Path, **kwargs: object) -> object:
    return run_request(
        workflow,
        params={"topic": "test"},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,
        **kwargs,
    )


def test_happy_stub_completes_and_records_source_tagged_result(tmp_path: Path) -> None:
    result = _run(STUBS / "succeeds", tmp_path)
    assert not isinstance(result, EnvBlocked | RunBusy)
    runs = tmp_path / "runs" / "succeeds"
    run_dirs = list(runs.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    video_dir = run_dir / "01"

    request = read_request(run_dir)
    assert request.status == "complete"
    assert request.ended_utc is not None
    assert request.started_utc
    assert request.params == {"topic": "test"}
    assert request.videos[0].status == "complete"

    video = read_video(video_dir)
    assert video.status == "complete"
    assert video.ended_utc is not None
    assert video.result == {"video": "final.mp4", "caption": "hello"}

    events = list(read_events(run_dir))
    assert events
    assert all(source == "01" for _, source, _ in events)
    bodies = [event for _, _, event in events]
    assert {"t": "log", "level": "info", "msg": "ok"} in bodies
    assert {"t": "result", "video": "final.mp4", "caption": "hello"} in bodies

    context = json.loads((video_dir / "context.json").read_text(encoding="utf-8"))
    assert Path(context["paths"]["video"]) == video_dir.resolve()
    assert Path(context["paths"]["artifacts"]) == (video_dir / "artifacts").resolve()
    assert Path(context["paths"]["steps"]) == (video_dir / ".steps").resolve()
    assert Path(context["paths"]["shared"]) == (run_dir / "shared").resolve()
    assert context["settings"] == {"topic": "test"}
    assert context["instructions"] == []
    assert context["secrets"] == {}
    assert context["previous"] is None
    assert context["shared"] is None


def test_failing_stub_marks_request_and_video_failed(tmp_path: Path) -> None:
    result = _run(STUBS / "fails", tmp_path)
    assert not isinstance(result, EnvBlocked | RunBusy)
    run_dir = next((tmp_path / "runs" / "fails").iterdir())
    request = read_request(run_dir)
    assert request.status == "failed"
    assert request.ended_utc is not None
    video = read_video(run_dir / "01")
    assert video.status == "failed"
    assert video.result is None
    bodies = [event for _, source, event in read_events(run_dir)]
    error_logs = [
        event for event in bodies if event.get("t") == "log" and event.get("level") == "error"
    ]
    assert error_logs
    assert any("boom" in str(event.get("msg")) for event in error_logs)
    assert all(source == "01" for _, source, _ in read_events(run_dir))


def test_env_blocked_creates_no_run_folder(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    result = run_request(
        STUBS / "succeeds",
        params={"topic": "test"},
        video_count=1,
        concurrency=1,
        runs_dir=runs_dir,
        ensure_env=lambda *_a, **_k: EnvBlocked(reason="Python 3.12 is required but not installed"),
    )
    assert isinstance(result, EnvBlocked)
    assert result.reason == "Python 3.12 is required but not installed"
    assert not runs_dir.exists() or not any(runs_dir.rglob("*"))


def test_single_active_guard_refuses_second_run(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()
    first_result: list[object] = []

    def hold_env(*_args: object, **_kwargs: object) -> EnvReady:
        started.set()
        assert release.wait(timeout=5)
        return EnvReady(python=Path(sys.executable))

    def first() -> None:
        first_result.append(
            run_request(
                STUBS / "succeeds",
                params={"topic": "test"},
                video_count=1,
                concurrency=1,
                runs_dir=tmp_path / "runs",
                ensure_env=hold_env,
            )
        )

    thread = threading.Thread(target=first)
    thread.start()
    assert started.wait(timeout=5)
    refused = run_request(
        STUBS / "succeeds",
        params={"topic": "test"},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs-other",
        ensure_env=_ready,
    )
    assert isinstance(refused, RunBusy)
    assert refused.workflow_id == "succeeds"
    release.set()
    thread.join(timeout=15)
    assert not thread.is_alive()
    assert first_result
    assert not isinstance(first_result[0], EnvBlocked | RunBusy)
    assert read_request(next((tmp_path / "runs" / "succeeds").iterdir())).status == "complete"
