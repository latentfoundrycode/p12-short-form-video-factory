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
from app.core.supervisor import _redact_secrets, _RunState, _scrub_result_secrets
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


# --- H18: an on-disk result.json is scrubbed of secret values best-effort (failure path too) ---


def test_scrub_result_secrets_redacts_an_on_disk_result(tmp_path: Path):
    # H18: on the prepare FAILURE path (prepare wrote result.json then exited non-zero) the
    # inline success-path redaction is skipped. The finally must scrub the file best-effort so a
    # leaked secret VALUE never persists on disk (result.json, unlike context.json, is served).
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps({"script": "hello", "leaked": "sk-secret-xyz"}), encoding="utf-8"
    )
    _scrub_result_secrets(result_path, frozenset({"sk-secret-xyz"}))
    dumped = result_path.read_text(encoding="utf-8")
    assert "sk-secret-xyz" not in dumped  # the injected value is gone from disk
    assert "[REDACTED]" in dumped
    assert "hello" in dumped  # non-secret content preserved


@pytest.mark.parametrize(
    "payload,secret_must_be_gone",
    [
        (None, False),  # prepare()->None writes result.json = null (the standard contract)
        ("sk-secret-xyz", True),  # a top-level JSON string secret must be redacted
        (["ok", "sk-secret-xyz"], True),  # a secret inside a top-level array must be redacted
        (42, False),  # a scalar must not crash
    ],
)
def test_scrub_result_secrets_handles_non_object_result(
    tmp_path: Path, payload: object, secret_must_be_gone: bool
):
    # result.json is whatever prepare returned/wrote — commonly `null` (prepare()->None), and
    # possibly a bare string/array. The scrub must NEVER raise (teardown runs it on every prepare,
    # success included) and must still redact a secret carried by a non-object payload.
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    _scrub_result_secrets(result_path, frozenset({"sk-secret-xyz"}))  # must not raise on any type
    on_disk = result_path.read_text(encoding="utf-8")
    json.loads(on_disk)  # still valid JSON
    if secret_must_be_gone:
        assert "sk-secret-xyz" not in on_disk


def test_scrub_result_secrets_survives_pathologically_nested_json(tmp_path: Path):
    # A hostile workflow can write a deeply nested result.json to make json.loads / the recursive
    # _redact_secrets raise RecursionError. That must NOT crash teardown (RecursionError is not
    # OSError/ValueError/TypeError), and the injected secret must still be stripped from disk — a
    # text-level fallback that does not parse JSON handles both.
    depth = 2000
    nested = "[" * depth + '"prefix sk-secret-xyz suffix"' + "]" * depth
    result_path = tmp_path / "result.json"
    result_path.write_text(nested, encoding="utf-8")
    _scrub_result_secrets(result_path, frozenset({"sk-secret-xyz"}))  # must not raise
    on_disk = result_path.read_text(encoding="utf-8")
    assert "sk-secret-xyz" not in on_disk  # the leaked value is gone despite the pathological depth


def test_scrub_result_secrets_survives_invalid_utf8(tmp_path: Path):
    # A hostile workflow can write result.json with invalid UTF-8 bytes. Decoding as UTF-8 raises
    # UnicodeDecodeError (a ValueError subclass, NOT OSError); teardown must not crash, and the
    # injected secret must still be stripped from disk. A byte-level fallback handles it.
    result_path = tmp_path / "result.json"
    result_path.write_bytes(b'{"leaked": "sk-secret-xyz"}\xff\xfe')
    _scrub_result_secrets(result_path, frozenset({"sk-secret-xyz"}))  # must not raise
    on_disk = result_path.read_bytes()
    assert b"sk-secret-xyz" not in on_disk  # the leaked value is gone despite invalid UTF-8


def test_scrub_result_secrets_fallback_strips_json_escaped_secret(tmp_path: Path):
    # Defence-in-depth: when structured redaction cannot run (here: an unparsable file, doubled
    # closing brace) and the secret contains a JSON meta-character, the byte-level fallback must
    # also strip the ESCAPED on-disk form, not just the plain value a downloader could decode back.
    secret = 'sk-"backslash\\-secret'
    escaped_inner = json.dumps(secret)[1:-1]  # how the value appears inside a JSON string on disk
    result_path = tmp_path / "result.json"
    result_path.write_text('{"leaked": "' + escaped_inner + '"}}', encoding="utf-8")
    _scrub_result_secrets(result_path, frozenset({secret}))
    on_disk = result_path.read_text(encoding="utf-8")
    assert escaped_inner not in on_disk  # the escaped on-disk form is stripped


def test_scrub_result_secrets_is_best_effort_on_missing_or_bad_file(tmp_path: Path):
    # Never raises: a missing file is a no-op, and unparsable JSON is left as-is (the download
    # block / event redaction remain the backstops); scrubbing must not crash the run teardown.
    missing = tmp_path / "absent.json"
    _scrub_result_secrets(missing, frozenset({"sk-secret-xyz"}))  # no file → no-op, no raise
    assert not missing.exists()
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    _scrub_result_secrets(bad, frozenset({"sk-secret-xyz"}))  # unparsable → no raise
    assert bad.read_text(encoding="utf-8") == "{not valid json"


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


def test_failed_prepare_result_secret_is_redacted_on_disk_and_download(tmp_path: Path):
    # H18: a prepare that writes shared/result.json with its secret then exits non-zero skips the
    # runner's success-path redaction. The failed-run result.json must still be scrubbed on disk
    # (the _run_prepare finally), and the download endpoint (which serves result.json, unlike the
    # blocked context.json) must never return the injected value.
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    shutil.copytree(
        _STUBS / "leaks_secret_prepare_fail", workflows_dir / "leaks_secret_prepare_fail"
    )
    (workflows_dir / "leaks_secret_prepare_fail" / "requirements.txt").write_text(
        "", encoding="utf-8"
    )
    client = TestClient(
        create_app(
            workflows_dir=workflows_dir,
            runs_dir=tmp_path / "runs",
            ensure_env=_ready,  # type: ignore[arg-type]
            secrets={"OPENROUTER_API_KEY": "sk-leaked-value"},  # type: ignore[arg-type]
        )
    )
    r = client.post(
        "/api/workflows/leaks_secret_prepare_fail/runs",
        json={"params": {}, "video_count": 1, "concurrency": 1},
    )
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        d = client.get(f"/api/workflows/leaks_secret_prepare_fail/runs/{run_id}")
        if d.status_code == 200 and d.json()["status"] in _TERMINAL:
            break
        time.sleep(0.05)

    results = list((tmp_path / "runs").rglob("result.json"))
    assert results, "prepare did not write result.json (trigger precondition not met)"
    for jf in (tmp_path / "runs").rglob("*.json"):
        assert "sk-leaked-value" not in jf.read_text(encoding="utf-8"), f"secret leaked into {jf}"
    # result.json is not served at all (like context.json), so the download exfil vector is closed
    # for any encoding; the on-disk best-effort redaction above is defence-in-depth.
    resp = client.get(
        f"/api/workflows/leaks_secret_prepare_fail/runs/{run_id}/files/shared/result.json"
    )
    assert resp.status_code == 404


def test_prepare_returning_none_completes_and_does_not_crash_in_scrub(tmp_path: Path):
    # H18 round-2 regression guard: prepare()->None writes result.json = null. The finally scrub
    # runs on every prepare (success included); it must not crash on a null (non-object) result.
    # A completed run proves prepare's finally did not raise a TypeError on the null result.json.
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    shutil.copytree(_STUBS / "prepare_none_completes", workflows_dir / "prepare_none_completes")
    (workflows_dir / "prepare_none_completes" / "requirements.txt").write_text("", encoding="utf-8")
    client = TestClient(
        create_app(
            workflows_dir=workflows_dir,
            runs_dir=tmp_path / "runs",
            ensure_env=_ready,  # type: ignore[arg-type]
        )
    )
    r = client.post(
        "/api/workflows/prepare_none_completes/runs",
        json={"params": {}, "video_count": 1, "concurrency": 1},
    )
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    status = ""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        d = client.get(f"/api/workflows/prepare_none_completes/runs/{run_id}")
        if d.status_code == 200 and d.json()["status"] in _TERMINAL:
            status = d.json()["status"]
            break
        time.sleep(0.05)
    assert status == "complete"  # prepare's null-result finally scrub did not crash
