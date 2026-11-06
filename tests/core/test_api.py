import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from backend.core.db import Database
from backend.main import create_app


def new_call(client, room="api"):
    response = client.post("/calls", json={"room": room})
    assert response.status_code == 201, response.text
    return response.json()["call_id"]


def verify(client, call_id):
    response = client.post(
        f"/calls/{call_id}/verify", json={"member_digits": "4417", "birth_month": 4}
    )
    assert response.status_code == 200, response.text


def armed(client, call_id):
    verify(client, call_id)
    prefix = f"/calls/{call_id}"
    assert (
        client.post(
            prefix + "/providers", json={"specialty": "primary care", "zip": "10023"}
        ).status_code
        == 200
    )
    assert (
        client.post(prefix + "/select", json={"provider_id": "P2"}).status_code == 200
    )
    offered = client.post(
        prefix + "/availability",
        json={
            "date_from": "2026-11-13",
            "date_to": "2026-11-13",
            "part_of_day": "afternoon",
        },
    )
    assert offered.status_code == 200, offered.text
    slot_id = offered.json()["slots"][0]["slot_id"]
    assert client.post(prefix + "/slot", json={"slot_id": slot_id}).status_code == 200
    preview = client.post(prefix + "/appointment/preview", json={})
    assert preview.status_code == 200, preview.text
    assert all(
        text in preview.json()["read_back"]
        for text in (
            "Maya",
            "in person",
            "Dr. Omar Haddad",
            "2026",
            "Eastern time",
        )
    )
    token = preview.json()["token"]
    assert (
        client.post(prefix + "/appointment/armed", json={"token": token}).status_code
        == 200
    )
    return token


def test_api_checkpoint_and_openapi(client):
    call_id = new_call(client)
    verify(client, call_id)
    result = client.post(
        f"/calls/{call_id}/providers",
        json={"specialty": "primary care", "zip": "10023"},
    )
    assert result.status_code == 200
    assert [p["id"] for p in result.json()["providers"]] == ["P2", "P4"]
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/now").json()["business_date"] == "2026-11-06"


def test_api_success_replay_and_call_scoped_reconciliation(client, clock):
    call_id = new_call(client)
    token = armed(client, call_id)
    clock.advance()
    turn = {"client_turn_id": "consent", "role": "user", "text": "book it"}
    assert client.post(f"/calls/{call_id}/turn", json=turn).status_code == 201
    assert client.post(f"/calls/{call_id}/turn", json=turn).status_code == 200
    first = client.post(f"/calls/{call_id}/appointment/confirm", json={"token": token})
    assert first.status_code == 201, first.text
    again = client.post(f"/calls/{call_id}/appointment/confirm", json={"token": token})
    assert again.status_code == 200 and again.json() == first.json()
    assert client.get(f"/calls/{call_id}/appointment").json()["appointments"] == [
        first.json()["appointment"]
    ]
    other_id = new_call(client, "other-room")
    verify(client, other_id)
    assert client.get(f"/calls/{other_id}/appointment").json()["appointments"] == []
    assert (
        client.post(
            f"/calls/{other_id}/appointment/confirm", json={"token": token}
        ).json()["error"]
        == "STALE_CONFIRMATION"
    )


def test_access_precedes_call_lookup_and_validation(client):
    response = client.post(
        "/calls/missing/verify",
        content="{",
        headers={"X-Agent-Key": "wrong", "Content-Type": "application/json"},
    )
    assert response.status_code == 401 and response.json()["error"] == "UNAUTHORIZED"
    response = client.post("/calls/missing/verify", json={})
    assert response.status_code == 404 and response.json()["error"] == "CALL_NOT_FOUND"
    call_id = new_call(client)
    response = client.post(
        f"/calls/{call_id}/appointment/confirm", json={"confirmed": True}
    )
    assert (
        response.status_code == 403
        and response.json()["error"] == "VERIFICATION_REQUIRED"
    )


@pytest.mark.parametrize(
    "body",
    [
        {"member_digits": 4417, "birth_month": 4},
        {"member_digits": "4417", "birth_month": True},
        {"member_digits": "4417", "birth_month": "4"},
        {"member_digits": "4417", "birth_month": 13},
        {"member_digits": "4417", "birth_month": 4, "member_id": "M1"},
        {},
    ],
)
def test_invalid_verification_requests_do_not_consume_attempts(client, db, body):
    call_id = new_call(client)
    response = client.post(f"/calls/{call_id}/verify", json=body)
    assert response.status_code == 422
    assert set(response.json()) == {"error", "speak"}
    assert response.json()["error"] == "INVALID_REQUEST"
    with db.snapshot() as conn:
        assert (
            conn.execute(
                "SELECT verification_attempts FROM calls WHERE id=?", (call_id,)
            ).fetchone()[0]
            == 0
        )


def test_malformed_json_and_unknown_fields_are_flat_errors(client):
    response = client.post(
        "/calls", content="{", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422 and response.json()["error"] == "INVALID_REQUEST"
    call_id = new_call(client)
    token = armed(client, call_id)
    for extra in (
        {"confirmed": True},
        {"yes": True},
        {"slot_id": "guessed"},
        {"member_id": "M1"},
    ):
        response = client.post(
            f"/calls/{call_id}/appointment/confirm", json={"token": token, **extra}
        )
        assert response.status_code == 422 and "detail" not in response.json()


def test_api_failures_and_state_transitions(client, db):
    call_id = new_call(client)
    token = armed(client, call_id)
    prefix = f"/calls/{call_id}"
    malformed = client.post(
        prefix + "/providers", json={"specialty": "primary care", "zip": "bad"}
    )
    assert malformed.json()["error"] == "INVALID_ZIP"
    with db.snapshot() as conn:
        before = dict(
            conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        )
    invalid_date = client.post(
        prefix + "/availability",
        json={"date_from": "2026-02-30", "date_to": "2026-11-13", "part_of_day": "any"},
    )
    assert invalid_date.json()["error"] == "INVALID_REQUEST"
    with db.snapshot() as conn:
        assert (
            dict(conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone())
            == before
        )
    no_match = client.post(
        prefix + "/providers", json={"specialty": "primary care", "zip": "90210"}
    )
    assert no_match.status_code == 404 and no_match.json()["error"] == "NO_MATCH"
    with db.snapshot() as conn:
        call = conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        assert call["request_version"] == before["request_version"] + 1
        assert call["selected_provider_id"] is None and call["current_draft_id"] is None
        assert (
            json.loads(call["providers_json"]) == []
            and json.loads(call["offered_slots_json"]) == []
        )
    assert (
        client.post(prefix + "/appointment/confirm", json={"token": token}).json()[
            "error"
        ]
        == "STALE_CONFIRMATION"
    )


def test_no_availability_clears_preview_and_preserves_latest_query(client, db):
    call_id = new_call(client)
    token = armed(client, call_id)
    prefix = f"/calls/{call_id}"
    response = client.post(
        prefix + "/availability",
        json={"date_from": "2026-11-07", "date_to": "2026-11-07", "part_of_day": "any"},
    )
    assert response.status_code == 404 and response.json()["error"] == "NO_AVAILABILITY"
    assert (
        client.post(prefix + "/appointment/confirm", json={"token": token}).json()[
            "error"
        ]
        == "STALE_CONFIRMATION"
    )
    with db.snapshot() as conn:
        call = conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        assert (
            json.loads(call["offered_slots_json"]) == []
            and call["current_draft_id"] is None
        )
        assert json.loads(call["availability_query_json"])["date_from"] == "2026-11-07"


def test_concurrent_http_confirmations(client, clock):
    call_ids = [new_call(client, f"http-race-{i}") for i in range(2)]
    tokens = [armed(client, call_id) for call_id in call_ids]
    clock.advance()
    for call_id in call_ids:
        client.post(
            f"/calls/{call_id}/turn",
            json={"client_turn_id": "yes", "role": "user", "text": "yes"},
        )
    barrier = Barrier(2)

    def confirm(pair):
        call_id, token = pair
        barrier.wait()
        return client.post(
            f"/calls/{call_id}/appointment/confirm", json={"token": token}
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(confirm, zip(call_ids, tokens)))
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert [r.json()["error"] for r in responses if r.status_code == 409] == [
        "SLOT_TAKEN"
    ]


def test_missing_key_fails_closed(db):
    from fastapi.testclient import TestClient

    with TestClient(create_app(database=db, agent_key="")) as client:
        assert (
            client.post("/calls", json={"room": "no-key"}).json()["error"]
            == "UNAUTHORIZED"
        )


def test_restart_preserves_booking_and_replay(client, db, clock):
    from fastapi.testclient import TestClient

    call_id = new_call(client)
    token = armed(client, call_id)
    clock.advance()
    client.post(
        f"/calls/{call_id}/turn",
        json={"client_turn_id": "yes", "role": "user", "text": "yes"},
    )
    booked = client.post(
        f"/calls/{call_id}/appointment/confirm", json={"token": token}
    ).json()
    restarted = Database(db.path, clock=clock)
    with TestClient(create_app(database=restarted, agent_key="test")) as other:
        response = other.post(
            f"/calls/{call_id}/appointment/confirm",
            json={"token": token},
            headers={"X-Agent-Key": "test"},
        )
        assert response.status_code == 200 and response.json() == booked


def test_call_and_turn_idempotency_conflicts_and_closed_calls(client, db, clock):
    call_id = new_call(client)
    replay = client.post("/calls", json={"room": "api"})
    assert replay.status_code == 200 and replay.json()["call_id"] == call_id
    body = {"client_turn_id": "turn-1", "role": "user", "text": "hello"}
    first = client.post(f"/calls/{call_id}/turn", json=body)
    assert client.post(f"/calls/{call_id}/turn", json=body).json() == first.json()
    assert (
        client.post(f"/calls/{call_id}/turn", json={**body, "text": "no"}).json()[
            "error"
        ]
        == "IDEMPOTENCY_CONFLICT"
    )
    with db.transaction() as conn:
        conn.execute(
            "UPDATE calls SET status='finalized',finalized_at=? WHERE id=?",
            ("2026-11-06T21:00:00Z", call_id),
        )
    assert (
        client.post(
            f"/calls/{call_id}/turn", json={**body, "client_turn_id": "new"}
        ).json()["error"]
        == "CALL_CLOSED"
    )
    assert (
        client.post(
            f"/calls/{call_id}/turn",
            json={**body, "client_turn_id": "late", "role": "assistant"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/calls/{call_id}/verify", json={"member_digits": "4417", "birth_month": 4}
        ).json()["error"]
        == "CALL_CLOSED"
    )
    assert client.post("/calls", json={"room": "api"}).json() == replay.json()


def test_database_busy_returns_flat_service_unavailable(client, db):
    call_id = new_call(client)
    previous_timeout = db.timeout
    db.timeout = 0.01
    blocker = db.connect()
    blocker.execute("BEGIN IMMEDIATE")
    try:
        response = client.post(
            f"/calls/{call_id}/turn",
            json={"client_turn_id": "busy", "role": "user", "text": "yes"},
        )
    finally:
        blocker.rollback()
        blocker.close()
        db.timeout = previous_timeout
    assert response.status_code == 503
    assert response.json()["error"] == "SERVICE_UNAVAILABLE"
    assert set(response.json()) == {"error", "speak"}


def test_unexpected_database_failure_returns_no_internal_details(client, db, clock):
    from fastapi.testclient import TestClient

    call_id = new_call(client)
    token = armed(client, call_id)
    clock.advance()
    client.post(
        f"/calls/{call_id}/turn",
        json={"client_turn_id": "yes", "role": "user", "text": "yes"},
    )
    with db.transaction() as conn:
        conn.execute(
            "CREATE TRIGGER reject_booking BEFORE INSERT ON appointments BEGIN SELECT RAISE(ABORT, 'sensitive test internals'); END"
        )
    with TestClient(client.app, raise_server_exceptions=False) as errors_client:
        response = errors_client.post(
            f"/calls/{call_id}/appointment/confirm",
            json={"token": token},
            headers={"X-Agent-Key": "core-test-key"},
        )
    assert response.status_code == 500 and response.json()["error"] == "INTERNAL_ERROR"
    assert set(response.json()) == {"error", "speak"} and token not in response.text
    assert "sensitive" not in response.text
    with db.snapshot() as conn:
        assert not conn.execute("SELECT 1 FROM appointments").fetchone()


def test_pending_newer_no_is_written_before_confirm(client, clock, monkeypatch):
    from backend.core import calls

    call_id = new_call(client)
    token = armed(client, call_id)
    clock.advance()
    client.post(
        f"/calls/{call_id}/turn",
        json={"client_turn_id": "old-yes", "role": "user", "text": "yes"},
    )
    clock.advance()
    entered, release = Event(), Event()
    original = calls.store_turn

    def delayed_turn(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)

    monkeypatch.setattr(calls, "store_turn", delayed_turn)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending_no = pool.submit(
            client.post,
            f"/calls/{call_id}/turn",
            json={"client_turn_id": "new-no", "role": "user", "text": "no"},
        )
        assert entered.wait(3)
        pending_confirm = pool.submit(
            client.post, f"/calls/{call_id}/appointment/confirm", json={"token": token}
        )
        try:
            # Confirm is admitted behind a turn that is still being written.
            assert not pending_confirm.done()
        finally:
            release.set()
        assert pending_no.result(timeout=3).status_code == 201
        result = pending_confirm.result(timeout=3)
    assert result.status_code == 409 and result.json()["error"] == "NOT_CONFIRMED"
