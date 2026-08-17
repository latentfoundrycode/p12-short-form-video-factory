import json
import subprocess
import sys
import threading
from pathlib import Path

from app.core.env import EnvBlocked, EnvReady
from app.core.records import read_events, read_request, read_video
from app.core.supervisor import RunBusy, run_request

STUBS = Path(__file__).resolve().parent.parent / "stubs"


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def _run(
    workflow: Path,
    tmp_path: Path,
    *,
    video_count: int = 1,
    concurrency: int = 1,
    **kwargs: object,
) -> object:
    return run_request(
        workflow,
        params={"topic": "test"},
        video_count=video_count,
        concurrency=concurrency,
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,
        **kwargs,
    )


def _assert_events_parse(run_dir: Path) -> None:
    path = run_dir / "events.jsonl"
    assert path.is_file()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        envelope = json.loads(line)
        assert isinstance(envelope, dict)
        assert isinstance(envelope["ts"], str)
        assert isinstance(envelope["source"], str)
        assert isinstance(envelope["event"], dict)


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


def test_prepare_feeds_shared_into_video_context(tmp_path: Path) -> None:
    seen_video_status: list[str] = []

    def wrapping_popen(*args: object, **kwargs: object) -> subprocess.Popen[str]:
        cwd = Path(str(kwargs["cwd"]))
        request = json.loads((cwd.parent / "request.json").read_text(encoding="utf-8"))
        if cwd.name == "01":
            seen_video_status.append(request["videos"][0]["status"])
        return subprocess.Popen(*args, **kwargs)  # type: ignore[arg-type]

    result = _run(STUBS / "prepares", tmp_path, popen=wrapping_popen)
    assert not isinstance(result, EnvBlocked | RunBusy)
    run_dir = next((tmp_path / "runs" / "prepares").iterdir())
    shared = json.loads((run_dir / "shared" / "result.json").read_text(encoding="utf-8"))
    assert shared == {"script": "hello from prep"}
    video_context = json.loads((run_dir / "01" / "context.json").read_text(encoding="utf-8"))
    assert video_context["shared"] == {"script": "hello from prep"}
    events = list(read_events(run_dir))
    prep_bodies = [event for _, source, event in events if source == "prep"]
    video_bodies = [event for _, source, event in events if source == "01"]
    assert {"t": "log", "level": "info", "msg": "prep-ok"} in prep_bodies
    assert {"t": "log", "level": "info", "msg": "hello from prep"} in video_bodies
    assert seen_video_status == ["running"]
    assert read_request(run_dir).videos[0].status == "complete"
    assert read_video(run_dir / "01").status == "complete"


def test_failed_prepare_fails_request_without_launching_video(tmp_path: Path) -> None:
    result = _run(STUBS / "prep_fails", tmp_path)
    assert not isinstance(result, EnvBlocked | RunBusy)
    run_dir = next((tmp_path / "runs" / "prep-fails").iterdir())
    request = read_request(run_dir)
    assert request.status == "failed"
    assert request.ended_utc is not None
    assert request.videos[0].status == "pending"
    assert not (run_dir / "01" / "video.json").exists()
    assert not (run_dir / "01" / "context.json").exists()
    bodies = [event for _, source, event in read_events(run_dir)]
    assert all(source == "prep" for _, source, _ in read_events(run_dir))
    assert any(
        event.get("t") == "log"
        and event.get("level") == "error"
        and "prep boom" in str(event.get("msg"))
        for event in bodies
    )


def test_stderr_from_workflow_becomes_log_event(tmp_path: Path) -> None:
    result = _run(STUBS / "stderr_noise", tmp_path)
    assert not isinstance(result, EnvBlocked | RunBusy)
    run_dir = next((tmp_path / "runs" / "stderr-noise").iterdir())
    bodies = [event for _, _, event in read_events(run_dir)]
    assert {"t": "log", "level": "info", "msg": "lib noise"} in bodies
    assert {"t": "log", "level": "info", "msg": "after stderr"} in bodies


def test_concurrency_below_video_count_completes_every_video(tmp_path: Path) -> None:
    result = _run(STUBS / "succeeds", tmp_path, video_count=3, concurrency=2)
    assert not isinstance(result, EnvBlocked | RunBusy)
    run_dir = next((tmp_path / "runs" / "succeeds").iterdir())
    request = read_request(run_dir)
    assert request.status == "complete"
    assert [video.status for video in request.videos] == ["complete", "complete", "complete"]
    _assert_events_parse(run_dir)
    sources = {source for _, source, _ in read_events(run_dir)}
    assert sources == {"01", "02", "03"}
    for name in ("01", "02", "03"):
        video = read_video(run_dir / name)
        assert video.status == "complete"
        assert video.result == {"video": "final.mp4", "caption": "hello"}
        bodies = [event for _, source, event in read_events(run_dir) if source == name]
        assert {"t": "log", "level": "info", "msg": "ok"} in bodies


def test_concurrency_at_least_video_count_completes_every_video(tmp_path: Path) -> None:
    result = _run(STUBS / "succeeds", tmp_path, video_count=3, concurrency=4)
    assert not isinstance(result, EnvBlocked | RunBusy)
    run_dir = next((tmp_path / "runs" / "succeeds").iterdir())
    request = read_request(run_dir)
    assert request.status == "complete"
    assert all(video.status == "complete" for video in request.videos)
    assert not any(video.status == "pending" for video in request.videos)
    _assert_events_parse(run_dir)
    assert {source for _, source, _ in read_events(run_dir)} == {"01", "02", "03"}


def test_mixed_non_atomic_request_is_partial(tmp_path: Path) -> None:
    result = _run(STUBS / "mixed_variants", tmp_path, video_count=3, concurrency=2)
    assert not isinstance(result, EnvBlocked | RunBusy)
    run_dir = next((tmp_path / "runs" / "mixed-variants").iterdir())
    request = read_request(run_dir)
    assert request.status == "partial"
    assert [video.status for video in request.videos] == ["complete", "failed", "complete"]
    assert not any(video.status == "pending" for video in request.videos)
    _assert_events_parse(run_dir)
    assert {source for _, source, _ in read_events(run_dir)} == {"01", "02", "03"}
    assert read_video(run_dir / "01").status == "complete"
    assert read_video(run_dir / "02").status == "failed"
    assert read_video(run_dir / "03").status == "complete"


def test_mixed_atomic_request_is_failed(tmp_path: Path) -> None:
    result = _run(STUBS / "mixed_atomic", tmp_path, video_count=3, concurrency=3)
    assert not isinstance(result, EnvBlocked | RunBusy)
    run_dir = next((tmp_path / "runs" / "mixed-atomic").iterdir())
    request = read_request(run_dir)
    assert request.status == "failed"
    assert [video.status for video in request.videos] == ["complete", "failed", "complete"]
    assert not any(video.status == "pending" for video in request.videos)
    _assert_events_parse(run_dir)


def test_all_failed_videos_aggregate_failed(tmp_path: Path) -> None:
    result = _run(STUBS / "fails", tmp_path, video_count=2, concurrency=2)
    assert not isinstance(result, EnvBlocked | RunBusy)
    run_dir = next((tmp_path / "runs" / "fails").iterdir())
    request = read_request(run_dir)
    assert request.status == "failed"
    assert [video.status for video in request.videos] == ["failed", "failed"]
    _assert_events_parse(run_dir)
    assert {source for _, source, _ in read_events(run_dir)} == {"01", "02"}
