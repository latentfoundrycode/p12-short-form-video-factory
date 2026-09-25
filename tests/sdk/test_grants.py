"""TASK-SSN-A2 contract: per-asset access grants for the owner library pool.

An owner-uploaded asset (music / SFX / voice) is grantable to ALL workflows or a chosen SET of
specific workflows. Grants are mutable metadata stored in `grants.json` in the owner-pool root
(shape like the library's `aliases.json`): `{"all": true}` or `{"workflows": [ids]}`. The store
validates the grant shape, persists it atomically, answers `grant_allows(asset_id, workflow_id)`,
and defaults an ungranted asset to deny (no workflow). Grants for an unknown/deleted workflow id are
stored and read back untouched (they are simply ignored by allow-checks for other workflows).

Supervisor-authored frozen contract (RED-first): written before the implementation; the builder
implements `sdk/sfvf/grants.py` to make it pass and touches no test file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sfvf.grants import GrantError, GrantStore


def _store(tmp_path: Path) -> GrantStore:
    return GrantStore(tmp_path / "_owner")


def test_grant_all_allows_any_workflow(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_grant("asset1", {"all": True})
    assert store.get_grant("asset1") == {"all": True}
    assert store.grant_allows("asset1", "sensational-science-news") is True
    assert store.grant_allows("asset1", "any-other") is True


def test_grant_specific_allows_only_listed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_grant("asset2", {"workflows": ["wf-a", "wf-b"]})
    assert store.get_grant("asset2") == {"workflows": ["wf-a", "wf-b"]}
    assert store.grant_allows("asset2", "wf-a") is True
    assert store.grant_allows("asset2", "wf-b") is True
    assert store.grant_allows("asset2", "wf-c") is False


def test_ungranted_asset_defaults_to_deny(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.get_grant("never-set") == {"workflows": []}
    assert store.grant_allows("never-set", "anything") is False


def test_grant_persists_across_store_instances(tmp_path: Path) -> None:
    _store(tmp_path).set_grant("asset3", {"workflows": ["wf-x"]})
    reopened = _store(tmp_path)  # new instance, same root -> reads grants.json
    assert reopened.get_grant("asset3") == {"workflows": ["wf-x"]}
    assert reopened.grant_allows("asset3", "wf-x") is True


def test_set_grant_overwrites(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_grant("asset4", {"workflows": ["wf-a"]})
    store.set_grant("asset4", {"all": True})
    assert store.get_grant("asset4") == {"all": True}


def test_grant_for_unknown_workflow_id_is_stored_and_read_back(tmp_path: Path) -> None:
    # A grant may reference a workflow id that no longer exists (e.g. a deleted workflow);
    # it is stored untouched and simply does not allow any *other* workflow.
    store = _store(tmp_path)
    store.set_grant("asset5", {"workflows": ["deleted-workflow"]})
    assert store.get_grant("asset5") == {"workflows": ["deleted-workflow"]}
    assert store.grant_allows("asset5", "deleted-workflow") is True
    assert store.grant_allows("asset5", "live-workflow") is False


@pytest.mark.parametrize(
    "bad",
    [
        {"bogus": 1},
        {"all": "yes"},          # all must be a bool
        {"workflows": "wf-a"},   # workflows must be a list
        {"workflows": [1, 2]},   # workflow ids must be strings
        {"all": True, "workflows": ["wf-a"]},  # exactly one form
        "not-a-dict",
        [],
    ],
)
def test_malformed_grant_is_rejected(tmp_path: Path, bad: object) -> None:
    store = _store(tmp_path)
    with pytest.raises(GrantError):
        store.set_grant("assetX", bad)  # type: ignore[arg-type]


# --- r2: fail-closed hardening (Review A + security-auditor) ---


def _grants_file(tmp_path: Path) -> Path:
    root = tmp_path / "_owner"
    root.mkdir(parents=True, exist_ok=True)
    return root / "grants.json"


def test_get_grant_returns_independent_default_deny_objects(tmp_path: Path) -> None:
    # The default-deny result must not alias a shared module constant: mutating one result
    # must never turn a later ungranted read into allow.
    store = _store(tmp_path)
    first = store.get_grant("x")
    first["workflows"].append("sneaky")
    assert store.get_grant("y") == {"workflows": []}
    assert store.grant_allows("y", "sneaky") is False


def test_get_grant_on_corrupt_file_fails_closed(tmp_path: Path) -> None:
    # A corrupt/unparseable grants.json must DENY on read (fail closed), not raise or allow.
    store = _store(tmp_path)
    _grants_file(tmp_path).write_text("{ this is not json", encoding="utf-8")
    assert store.get_grant("anything") == {"workflows": []}
    assert store.grant_allows("anything", "wf") is False


def test_get_grant_on_invalid_stored_entry_fails_closed(tmp_path: Path) -> None:
    # An entry whose stored shape set_grant would have rejected (e.g. both keys) must DENY.
    import json

    store = _store(tmp_path)
    _grants_file(tmp_path).write_text(
        json.dumps({"a": {"all": True, "workflows": ["wf"]}}), encoding="utf-8"
    )
    assert store.get_grant("a") == {"workflows": []}
    assert store.grant_allows("a", "wf") is False


def test_set_grant_on_corrupt_file_raises_without_data_loss(tmp_path: Path) -> None:
    # Writing must FAIL LOUD on a corrupt file (never silently overwrite/lose grants).
    store = _store(tmp_path)
    corrupt = _grants_file(tmp_path)
    corrupt.write_text("{ not json", encoding="utf-8")
    with pytest.raises(GrantError):
        store.set_grant("a", {"all": True})
    assert corrupt.read_text(encoding="utf-8") == "{ not json"  # untouched
