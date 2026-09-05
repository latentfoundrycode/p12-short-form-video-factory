"""S2c contract: secret VALUES are redacted from the event stream (§5.6 defense-in-depth).

All run events — subprocess stdout, silence-watcher notes, log lines, error messages — flow
through `_RunState.record_event` before landing in `events.jsonl` (and the SSE feed). If a
workflow accidentally emits one of its injected secret values, it must be replaced with
`[REDACTED]` rather than persisted. `_redact_secrets` does the scrubbing; `_RunState` carries
the run's secret values. Fake values live only under tmp_path.
"""

import json
from pathlib import Path

from app.core.supervisor import _redact_secrets, _RunState


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
