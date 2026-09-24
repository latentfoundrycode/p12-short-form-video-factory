"""`sfvf.emit.heartbeat_during` — periodic heartbeats around a blocking local op (H6).

`finalize` and `media.edit` run FFmpeg synchronously with its output captured, so the workflow
subprocess produces no stdout during a long encode/concat and the supervisor's silence watchdog
(§2.8, 300 s) could kill a legitimately long op. `heartbeat_during` emits a `heartbeat` event
periodically from a daemon thread while the wrapped op runs, resetting the watchdog. `emit` writes
to stdout under a module lock, so emitting from the helper thread is safe.
"""

from __future__ import annotations

import json
import time

from sfvf.emit import heartbeat_during


def _heartbeats(out: str) -> list[dict]:
    events = [json.loads(line) for line in out.splitlines() if line.strip()]
    return [e for e in events if e.get("t") == "heartbeat"]


def test_heartbeat_during_emits_periodically_while_blocked(capsys) -> None:
    with heartbeat_during("finalize", waiting_on="ffmpeg", interval=0.02):
        time.sleep(0.5)
    hbs = _heartbeats(capsys.readouterr().out)
    assert len(hbs) >= 2  # a long op keeps the watchdog fed
    assert all(e["name"] == "finalize" and e["waiting_on"] == "ffmpeg" for e in hbs)


def test_heartbeat_during_emits_nothing_for_a_fast_op(capsys) -> None:
    # An op that finishes before the first interval emits no heartbeats (no watchdog risk).
    with heartbeat_during("finalize", waiting_on="ffmpeg", interval=30.0):
        pass
    assert _heartbeats(capsys.readouterr().out) == []


def test_heartbeat_during_stops_after_the_block_exits(capsys) -> None:
    with heartbeat_during("edit", waiting_on="ffmpeg", interval=0.02):
        time.sleep(0.1)
    capsys.readouterr()  # drain heartbeats emitted during the block
    time.sleep(0.1)  # the daemon thread must have stopped; no more heartbeats after exit
    assert _heartbeats(capsys.readouterr().out) == []
