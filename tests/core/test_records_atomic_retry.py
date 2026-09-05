"""H7 fix: atomic-record I/O is resilient to the Windows atomic-replace/open race.

On windows-latest CI, `write_json_atomic`'s `os.replace(tmp, path)` and a concurrent
`read_json(path)` collide: while a workflow subprocess replaces `video.json`/`request.json`,
a reader opening the same file (or the replace itself, if a reader holds it) hits a transient
`PermissionError [Errno 13]` (Windows file-sharing violation). The atomic swap completes in
microseconds, so a small bounded retry on `PermissionError` — around BOTH the replace and the
read — removes the flake without weakening anything. This pins that behaviour deterministically
by injecting the transient error rather than trying to reproduce the race.

The retry delay is tuned to 0 here so the tests stay fast.
"""

import os

import pytest

from app.core import records


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the bounded retry, but don't actually sleep between attempts.
    monkeypatch.setattr(records, "_RETRY_DELAY_S", 0.0)


def test_write_json_atomic_retries_replace_on_transient_permission_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "video.json"
    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst, *a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:  # first two attempts hit the sharing violation
            raise PermissionError(13, "Permission denied")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", flaky_replace)
    records.write_json_atomic(path, {"status": "complete"})

    assert calls["n"] == 3  # retried twice, succeeded on the third
    assert records.read_json(path) == {"status": "complete"}
    # No leftover temp files beside the target.
    assert [p.name for p in tmp_path.iterdir()] == ["video.json"]


def test_write_json_atomic_reraises_and_cleans_up_after_exhausting_retries(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "request.json"

    def always_denied(src, dst, *a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "replace", always_denied)
    with pytest.raises(PermissionError):
        records.write_json_atomic(path, {"status": "running"})

    # The target was never created, and the temp file was cleaned up (no `.tmp` leftovers).
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_read_json_retries_on_transient_permission_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "video.json"
    records.write_json_atomic(path, {"status": "complete"})

    from pathlib import Path

    real_read_text = Path.read_text
    calls = {"n": 0}

    def flaky_read_text(self, *a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(13, "Permission denied")
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    assert records.read_json(path) == {"status": "complete"}
    assert calls["n"] == 3


def test_read_json_reraises_after_exhausting_retries(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "video.json"
    records.write_json_atomic(path, {"status": "complete"})

    from pathlib import Path

    def always_denied(self, *a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_text", always_denied)
    with pytest.raises(PermissionError):
        records.read_json(path)


def test_round_trip_happy_path_unaffected(tmp_path) -> None:
    # No injected error: normal write/read still works with no retries needed.
    path = tmp_path / "request.json"
    records.write_json_atomic(path, {"status": "running", "n": 1})
    assert records.read_json(path) == {"status": "running", "n": 1}
