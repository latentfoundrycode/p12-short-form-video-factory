"""F-3 contract: the schedules CRUD API (Architecture §5.7, `/schedule` page §8.6).

§5.7: "Reads `schedules.json`. When an entry is due it checks two conditions … if that workflow
already has an active run, the slot is skipped; if the budget is insufficient, the slot is skipped.
Otherwise the Generation Request starts with the saved settings … Missed slots are skipped rather
than queued … Each entry carries the flag determining whether approval gates pause or pass
automatically."

F-1 (`app/core/schedules.py`) froze the data layer: a validated `ScheduleEntry` and atomic
read/write of `schedules.json`. F-2 (`app/core/scheduler.py`) froze the pure engine that evaluates
due-ness. This increment (F-3) is the REST surface the `/schedule` page (v-schedule mockup: a list
of entries + Add entry + Edit) drives to manage that file: list, create, read-one, update, delete.

Contract decisions locked here (the supervisor's, not §5.7's — the spec is silent on the API shape):
  * Route prefix `/api/schedules`; envelope `{"schedules": [entry, ...]}` on list.
  * Each entry object carries exactly the nine `ScheduleEntry` fields.
  * The server GENERATES the `id` on create (opaque, stable, a safe path segment); clients never
    supply or change it — the create/update body carries only the writable fields (extra="forbid").
  * Create → 201 with the full stored entry; update/delete address an existing entry by `id` in
    the path and 404 when it is absent; delete → 204.
  * Invalid input (bad `time_of_day`, empty/out-of-range `days`, `video_count` < 1, an unknown
    field) → 422 and the stored file is left unchanged. Owner decision (2026-09-12):
    `allow_real_spend` defaults False and `concurrency` defaults 1, mirroring the model.
  * Persistence goes through `app.core.schedules.read_schedules`/`write_schedules` on the path in
    `app.state.schedules_path`, injected via `create_app(schedules_path=...)`. Read-modify-write is
    serialised so concurrent writers cannot lose an update. Workflow existence is NOT checked at
    CRUD time (schedules are decoupled from the live registry, as `schedules.json` already is; a due
    slot for an unknown workflow is the scheduler's skip to make, not the CRUD layer's).

No network, no runs started here.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.schedules import read_schedules
from app.main import create_app

ENTRY_FIELDS = {
    "id",
    "workflow_id",
    "days",
    "time_of_day",
    "video_count",
    "concurrency",
    "params",
    "gates_auto",
    "allow_real_spend",
}


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    schedules_path = tmp_path / "schedules.json"
    return TestClient(create_app(schedules_path=schedules_path)), schedules_path


def _body(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "workflow_id": "explainer",
        "days": [0, 2, 4],
        "time_of_day": "07:00",
        "video_count": 3,
        "params": {"topic": "physics"},
        "gates_auto": True,
    }
    base.update(overrides)
    return base


def test_list_is_empty_when_file_absent(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get("/api/schedules")
    assert response.status_code == 200
    assert response.json() == {"schedules": []}


def test_create_returns_stored_entry_with_generated_id_and_defaults(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.post("/api/schedules", json=_body())
    assert response.status_code == 201
    entry = response.json()
    assert set(entry) == ENTRY_FIELDS
    assert entry["id"]  # server-generated, non-empty
    assert entry["workflow_id"] == "explainer"
    assert entry["days"] == [0, 2, 4]
    assert entry["time_of_day"] == "07:00"
    assert entry["video_count"] == 3
    assert entry["params"] == {"topic": "physics"}
    assert entry["gates_auto"] is True
    # Owner decision: a scheduled run is a free dry run unless real spend is explicitly enabled.
    assert entry["allow_real_spend"] is False
    assert entry["concurrency"] == 1


def test_create_persists_through_the_schedules_module(tmp_path: Path) -> None:
    client, schedules_path = _client(tmp_path)
    created = client.post("/api/schedules", json=_body(workflow_id="collage")).json()
    stored = read_schedules(schedules_path)
    assert [e.id for e in stored] == [created["id"]]
    assert stored[0].workflow_id == "collage"


def test_create_then_list_returns_the_entry(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    created = client.post("/api/schedules", json=_body()).json()
    listed = client.get("/api/schedules").json()["schedules"]
    assert [e["id"] for e in listed] == [created["id"]]


def test_created_ids_are_unique(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    first = client.post("/api/schedules", json=_body()).json()["id"]
    second = client.post("/api/schedules", json=_body()).json()["id"]
    assert first != second
    assert len(client.get("/api/schedules").json()["schedules"]) == 2


def test_create_allows_opting_into_real_spend_and_concurrency(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    entry = client.post(
        "/api/schedules",
        json=_body(allow_real_spend=True, concurrency=2),
    ).json()
    assert entry["allow_real_spend"] is True
    assert entry["concurrency"] == 2


def test_create_rejects_invalid_time_of_day(tmp_path: Path) -> None:
    client, schedules_path = _client(tmp_path)
    response = client.post("/api/schedules", json=_body(time_of_day="7am"))
    assert response.status_code == 422
    assert read_schedules(schedules_path) == []


def test_create_rejects_empty_days(tmp_path: Path) -> None:
    client, schedules_path = _client(tmp_path)
    response = client.post("/api/schedules", json=_body(days=[]))
    assert response.status_code == 422
    assert read_schedules(schedules_path) == []


def test_create_rejects_weekday_out_of_range(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.post("/api/schedules", json=_body(days=[0, 7])).status_code == 422


def test_create_rejects_video_count_below_one(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.post("/api/schedules", json=_body(video_count=0)).status_code == 422


def test_create_rejects_unknown_field(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.post("/api/schedules", json=_body(surprise="x")).status_code == 422


def test_create_ignores_a_client_supplied_id(tmp_path: Path) -> None:
    # `id` is not a writable field; sending one is an unknown field, rejected.
    client, _ = _client(tmp_path)
    assert client.post("/api/schedules", json=_body(id="mine")).status_code == 422


def test_get_one_returns_entry_and_404s_when_absent(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    created = client.post("/api/schedules", json=_body()).json()
    found = client.get(f"/api/schedules/{created['id']}")
    assert found.status_code == 200
    assert found.json() == created
    assert client.get("/api/schedules/no-such-id").status_code == 404


def test_update_replaces_writable_fields_and_keeps_id(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    created = client.post("/api/schedules", json=_body()).json()
    updated = client.put(
        f"/api/schedules/{created['id']}",
        json=_body(video_count=5, days=[5, 6], time_of_day="09:30", gates_auto=False),
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["id"] == created["id"]
    assert payload["video_count"] == 5
    assert payload["days"] == [5, 6]
    assert payload["time_of_day"] == "09:30"
    assert payload["gates_auto"] is False
    # The change is visible on a fresh read and there is still exactly one entry.
    listed = client.get("/api/schedules").json()["schedules"]
    assert listed == [payload]


def test_update_unknown_id_is_404_and_creates_nothing(tmp_path: Path) -> None:
    client, schedules_path = _client(tmp_path)
    assert client.put("/api/schedules/no-such-id", json=_body()).status_code == 404
    assert read_schedules(schedules_path) == []


def test_update_rejects_invalid_body(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    created = client.post("/api/schedules", json=_body()).json()
    response = client.put(f"/api/schedules/{created['id']}", json=_body(time_of_day="24:00"))
    assert response.status_code == 422
    # The stored entry is untouched by a rejected update.
    assert client.get(f"/api/schedules/{created['id']}").json() == created


def test_delete_removes_the_entry(tmp_path: Path) -> None:
    client, schedules_path = _client(tmp_path)
    created = client.post("/api/schedules", json=_body()).json()
    deleted = client.delete(f"/api/schedules/{created['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/schedules/{created['id']}").status_code == 404
    assert read_schedules(schedules_path) == []


def test_delete_unknown_id_is_404(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.delete("/api/schedules/no-such-id").status_code == 404


def test_delete_leaves_other_entries(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    keep = client.post("/api/schedules", json=_body(workflow_id="keep")).json()
    drop = client.post("/api/schedules", json=_body(workflow_id="drop")).json()
    assert client.delete(f"/api/schedules/{drop['id']}").status_code == 204
    listed = client.get("/api/schedules").json()["schedules"]
    assert [e["id"] for e in listed] == [keep["id"]]
