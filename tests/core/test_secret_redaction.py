"""S2c contract: secret VALUES are redacted from the event stream (§5.6 defense-in-depth).

All run events — subprocess stdout, silence-watcher notes, log lines, error messages — flow
through `_RunState.record_event` before landing in `events.jsonl` (and the SSE feed). If a
workflow accidentally emits one of its injected secret values, it must be replaced with
`[REDACTED]` rather than persisted. `_redact_secrets` does the scrubbing; `_RunState` carries
the run's secret values. Fake values live only under tmp_path.
"""

import json
import shutil
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.core.supervisor as supervisor_mod
from app.core.env import EnvReady
from app.core.supervisor import _redact_secrets, _RunState
from app.main import create_app

_STUBS = Path(__file__).resolve().parent.parent / "stubs"
_TERMINAL = {"complete", "partial", "stopped", "stopped-budget", "failed"}


def test_redact_secrets_scrubs_nested_string_values():
    obj = {
        "msg": "key is sk-abc123 and again sk-abc123",
        "count": 5,
        "flag": True,
        "nested": ["sk-abc123", "harmless", {"deep": "prefix sk-abc123 suffix"}],
    }
    out = _redact_secrets(obj, frozenset({"sk-abc123"}))
    dumped = json.dumps(out)
    assert "sk-abc123" not in dumped  # every occurrence, at any depth, is gone
    assert "[REDACTED]" in dumped
    assert out["count"] == 5  # non-strings untouched
    assert out["flag"] is True
    assert "harmless" in dumped  # non-secret strings preserved


def test_redact_secrets_no_values_is_identity():
    obj = {"msg": "nothing secret here", "n": 1}
    assert _redact_secrets(obj, frozenset()) == obj


def test_record_event_redacts_secret_values(tmp_path: Path):
    state = _RunState(secret_values=frozenset({"sk-secret-xyz"}))
    state.record_event(
        tmp_path, {"t": "log", "level": "info", "msg": "leaked sk-secret-xyz mid-line"}, "runner"
    )
    text = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "sk-secret-xyz" not in text
    assert "[REDACTED]" in text


def test_record_event_without_secrets_is_verbatim(tmp_path: Path):
    state = _RunState()  # no secret values configured
    state.record_event(tmp_path, {"t": "log", "level": "info", "msg": "ordinary line"}, "runner")
    text = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "ordinary line" in text


def test_record_event_empty_secret_string_is_ignored(tmp_path: Path):
    # An empty string must never be treated as a secret (it would "match" everywhere).
    state = _RunState(secret_values=frozenset({""}))
    state.record_event(tmp_path, {"t": "log", "msg": "hello world"}, "runner")
    text = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "hello world" in text
    assert "[REDACTED]" not in text


def test_redact_secrets_scrubs_dict_keys(tmp_path: Path):
    # A secret used as a dict KEY must also be scrubbed, not just values.
    out = _redact_secrets({"sk-abc123": "value"}, frozenset({"sk-abc123"}))
    assert "sk-abc123" not in json.dumps(out)
    assert "[REDACTED]" in json.dumps(out)


def test_redact_secrets_handles_overlapping_values():
    # When one secret value is a prefix of another, redaction must not leave a
    # dangling suffix of the longer value. Longest match must win regardless of
    # frozenset iteration order.
    values = frozenset({"sk-ab", "sk-abcdefghij"})
    out = _redact_secrets({"msg": "here is sk-abcdefghij in a line"}, values)
    dumped = json.dumps(out)
    assert "sk-ab" not in dumped  # no prefix left
    assert "cdefghij" not in dumped  # no suffix of the longer value left
    assert "[REDACTED]" in dumped


# --- integration: a secret in a workflow's structured result must not persist in video.json ---


@pytest.fixture(autouse=True)
def _clear_supervisor_state():
    with supervisor_mod._lock:
        supervisor_mod._active.clear()
        supervisor_mod._runs.clear()
    yield
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with supervisor_mod._lock:
            if not supervisor_mod._active and not supervisor_mod._runs:
                break
        time.sleep(0.05)
    with supervisor_mod._lock:
        supervisor_mod._active.clear()
        supervisor_mod._runs.clear()


def _ready(*_a: object, **_k: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def test_result_secret_is_redacted_in_video_json(tmp_path: Path):
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    shutil.copytree(_STUBS / "leaks_secret", workflows_dir / "leaks_secret")
    (workflows_dir / "leaks_secret" / "requirements.txt").write_text("", encoding="utf-8")
    client = TestClient(
        create_app(
            workflows_dir=workflows_dir,
            runs_dir=tmp_path / "runs",
            ensure_env=_ready,  # type: ignore[arg-type]
            secrets={"OPENROUTER_API_KEY": "sk-leaked-value"},  # type: ignore[arg-type]
        )
    )
    r = client.post(
        "/api/workflows/leaks_secret/runs",
        json={"params": {}, "video_count": 1, "concurrency": 1},
    )
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        d = client.get(f"/api/workflows/leaks_secret/runs/{run_id}")
        if d.status_code == 200 and d.json()["status"] in _TERMINAL:
            break
        time.sleep(0.05)

    videos = list((tmp_path / "runs").rglob("video.json"))
    assert videos, "no video.json written"
    for vj in videos:
        text = vj.read_text(encoding="utf-8")
        assert "sk-leaked-value" not in text, f"secret leaked into {vj}"
    # events.jsonl must also be clean
    for ev in (tmp_path / "runs").rglob("events.jsonl"):
        assert "sk-leaked-value" not in ev.read_text(encoding="utf-8")


def test_prepare_result_secret_is_redacted(tmp_path: Path):
    # A prepare step's return value is written to shared/result.json (directly by the
    # runner) and threaded into each video's context.json `shared` payload. Neither the
    # on-disk result.json nor any context.json may persist an injected secret verbatim.
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    shutil.copytree(_STUBS / "leaks_secret_prepare", workflows_dir / "leaks_secret_prepare")
    (workflows_dir / "leaks_secret_prepare" / "requirements.txt").write_text("", encoding="utf-8")
    client = TestClient(
        create_app(
            workflows_dir=workflows_dir,
            runs_dir=tmp_path / "runs",
            ensure_env=_ready,  # type: ignore[arg-type]
            secrets={"OPENROUTER_API_KEY": "sk-leaked-value"},  # type: ignore[arg-type]
        )
    )
    r = client.post(
        "/api/workflows/leaks_secret_prepare/runs",
        json={"params": {}, "video_count": 1, "concurrency": 1},
    )
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        d = client.get(f"/api/workflows/leaks_secret_prepare/runs/{run_id}")
        if d.status_code == 200 and d.json()["status"] in _TERMINAL:
            break
        time.sleep(0.05)

    results = list((tmp_path / "runs").rglob("result.json"))
    assert results, "no result.json written"
    # Every JSON record under the run tree must be free of the secret value.
    for jf in (tmp_path / "runs").rglob("*.json"):
        assert "sk-leaked-value" not in jf.read_text(encoding="utf-8"), f"secret leaked into {jf}"
    for ev in (tmp_path / "runs").rglob("events.jsonl"):
        assert "sk-leaked-value" not in ev.read_text(encoding="utf-8")
