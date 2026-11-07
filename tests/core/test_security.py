"""Security regressions exercise the real HTTP boundary and persistent state."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.core.db import Database
from backend.core.seed import seed
from backend.credentials import rotate, write_private
from backend.main import create_app
from backend.security import SecuritySettings, digest

AGENT = "service-agent-secret-at-least-32-characters"
CALL_A = "call-a-capability-at-least-32-characters"
CALL_B = "call-b-capability-at-least-32-characters"


def record(secret=AGENT, **extra):
    return {
        "subject": "voice-worker",
        "organization": "org-a",
        "role": "agent",
        "sha256": digest(secret),
        "not_before": "2020-01-01T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        **extra,
    }


def private_json(path, payload):
    write_private(path, json.dumps(payload))
    return str(path)


@pytest.fixture
def secured(tmp_path, clock):
    settings = SecuritySettings(
        organization="org-a",
        credentials_file=private_json(tmp_path / "credentials", [record()]),
        identity_policy="reviewed-policy-test-v1",
    )
    db = Database(tmp_path / "security.db", clock=clock)
    with TestClient(create_app(database=db, security=settings)) as client:
        client.headers.update({"X-Agent-Key": AGENT, "X-Call-Key": CALL_A})
        yield client, db, settings


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/calls"),
        ("GET", "/now"),
        ("POST", "/calls/unknown/verify"),
        ("POST", "/calls/unknown/turn"),
        ("POST", "/calls/unknown/providers"),
        ("POST", "/calls/unknown/select"),
        ("POST", "/calls/unknown/dates"),
        ("POST", "/calls/unknown/availability"),
        ("POST", "/calls/unknown/slot"),
        ("POST", "/calls/unknown/appointment/preview"),
        ("POST", "/calls/unknown/appointment/armed"),
        ("POST", "/calls/unknown/appointment/confirm"),
        ("GET", "/calls/unknown/appointment"),
        ("GET", "/calls/latest"),
        ("GET", "/calls/history"),
        ("GET", "/calls/unknown/state"),
        ("GET", "/tasks"),
        ("POST", "/tasks/unknown/complete"),
        ("GET", "/providers/directory"),
        ("POST", "/admin/reset"),
        ("POST", "/admin/take-slot"),
        ("POST", "/calls/unknown/followup"),
        ("POST", "/calls/unknown/finalize"),
        ("POST", "/identity/calls/unknown/review"),
    ],
)
def test_every_route_rejects_unauthorized_before_body_validation(secured, method, path):
    client, _, _ = secured
    response = client.request(
        method, path, content="{", headers={"X-Agent-Key": "wrong"}
    )
    assert response.status_code == 401
    assert set(response.json()) == {"error", "speak"}
    assert response.headers["cache-control"] == "no-store"


def test_call_id_room_or_booking_token_never_authorize_another_call(secured):
    client, db, _ = secured
    call_id = client.post("/calls", json={"room": "patient-a"}).json()["call_id"]
    assert (
        client.post(
            f"/calls/{call_id}/verify", json={"member_digits": "4417", "birth_month": 4}
        ).status_code
        == 200
    )
    for capability in ("", CALL_B):
        headers = {"X-Call-Key": capability}
        for method, suffix in (
            ("GET", "appointment"),
            ("POST", "turn"),
            ("POST", "verify"),
            ("POST", "appointment/confirm"),
            ("POST", "followup"),
            ("POST", "finalize"),
        ):
            response = client.request(
                method, f"/calls/{call_id}/{suffix}", content="{", headers=headers
            )
            assert response.status_code == 403
        assert (
            client.post(
                "/calls", json={"room": "patient-a"}, headers=headers
            ).status_code
            == 403
        )
    with db.snapshot() as conn:
        assert not conn.execute("SELECT 1 FROM turns").fetchone()
        assert not conn.execute("SELECT 1 FROM appointments").fetchone()
        assert (
            conn.execute("SELECT status FROM calls WHERE id=?", (call_id,)).fetchone()[
                0
            ]
            == "live"
        )
        assert (
            CALL_A not in conn.execute("SELECT key_hash FROM call_access").fetchone()[0]
        )


def test_organization_role_subject_expiry_and_revocation(secured):
    client, _, settings = secured
    call_id = client.post("/calls", json={"room": "owner"}).json()["call_id"]
    for overrides in (
        {"organization": "org-b"},
        {"role": "operator"},
        {"subject": "other-worker"},
        {"expires_at": "2020-01-01T00:00:01Z"},
        {"not_before": "2098-01-01T00:00:00Z"},
    ):
        private_json(settings.credentials_file, [record(**overrides)])
        assert client.post(f"/calls/{call_id}/verify", json={}).status_code in {
            401,
            403,
        }
    private_json(settings.credentials_file, [])
    assert client.get("/now").status_code == 401


def test_agent_cannot_read_console_or_review_identity(secured):
    client, _, _ = secured
    for path in (
        "/calls/latest",
        "/calls/history",
        "/providers/directory",
        "/tasks",
        "/calls/x/state",
    ):
        assert client.get(path).status_code == 403
    assert client.post("/identity/calls/x/review", content="{").status_code == 403


def test_concurrent_call_capabilities_and_patient_results_are_isolated(secured):
    client, db, _ = secured
    calls = [
        client.post(
            "/calls", json={"room": f"patient-{index}"}, headers={"X-Call-Key": key}
        ).json()["call_id"]
        for index, key in enumerate((CALL_A, CALL_B))
    ]

    def verify(pair):
        index, key = pair
        return client.post(
            f"/calls/{calls[index]}/verify",
            json={
                "member_digits": ("4417", "2261")[index],
                "birth_month": (4, 6)[index],
            },
            headers={"X-Call-Key": key},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(verify, enumerate((CALL_A, CALL_B))))
    assert [response.json()["member"]["name"] for response in results] == [
        "Maya T.",
        "Riley C.",
    ]

    def swapped(index):
        return client.post(
            f"/calls/{calls[index]}/turn",
            json={"client_turn_id": "same-id", "role": "user", "text": "yes"},
            headers={"X-Call-Key": (CALL_B, CALL_A)[index]},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert [r.status_code for r in pool.map(swapped, range(2))] == [403, 403]
    with db.snapshot() as conn:
        assert not conn.execute("SELECT 1 FROM turns").fetchone()


def test_database_cannot_be_relabelled_or_seeded_as_production(secured):
    _, db, _ = secured
    other = Database(db.path)
    other.organization = "org-b"
    with pytest.raises(ValueError, match="mismatch"):
        other.initialize()
    db.environment = "production"
    with pytest.raises(ValueError, match="forbidden"):
        seed(db)
    with pytest.raises(ValueError, match="mismatch"):
        db.initialize()


def test_rotation_preserves_subject_but_revoked_key_stops_working(secured, tmp_path):
    client, _, settings = secured
    call_id = client.post("/calls", json={"room": "rotating"}).json()["call_id"]
    token_file = tmp_path / "agent.secret"
    rotate(settings.credentials_file, token_file, "voice-worker", "org-a", "agent")
    client.headers["X-Agent-Key"] = token_file.read_text()
    assert (
        client.post(
            f"/calls/{call_id}/verify", json={"member_digits": "4417", "birth_month": 4}
        ).status_code
        == 200
    )
    records = json.loads(Path(settings.credentials_file).read_text())
    private_json(settings.credentials_file, records[1:])
    assert client.get("/now", headers={"X-Agent-Key": AGENT}).status_code == 401


@pytest.fixture
def production(tmp_path, clock):
    from dataclasses import asdict

    from backend.lifecycle import RetentionPolicy

    settings = SecuritySettings(
        environment="production",
        organization="org-a",
        identity_policy="reviewed-policy-test-v1",
        credentials_file=private_json(
            tmp_path / "prod-credentials",
            [
                record(),
                record(
                    "review-secret-at-least-32-characters",
                    role="identity_reviewer",
                    subject="reviewer-1",
                ),
            ],
        ),
        retention_policy_file=private_json(
            tmp_path / "policy",
            asdict(
                RetentionPolicy(
                    "test-only-policy",
                    "test-approver",
                    "2026-01-01T00:00:00Z",
                    3,
                    30,
                    14,
                    5,
                    7,
                    2,
                )
            ),
        ),
        storage_evidence_file=private_json(
            tmp_path / "evidence",
            {
                "organization": "org-a",
                "encrypted_volume_id": "test-volume",
                "database_directory": str(tmp_path),
                "restricted_access_review": "test-review",
                "encrypted_backup_location": "test-vault",
                "recovery_test_reference": "test-drill",
                "valid_until": "2099-01-01T00:00:00Z",
            },
        ),
    )
    db = Database(tmp_path / "production.db", clock=clock)
    with TestClient(
        create_app(database=db, security=settings), base_url="https://backend.test"
    ) as client:
        client.headers.update({"X-Agent-Key": AGENT, "X-Call-Key": CALL_A})
        with db.transaction() as conn:
            assert conn.execute("SELECT count(*) FROM members").fetchone()[0] == 0
            conn.execute(
                "INSERT INTO plans (id,name,network) VALUES ('test-plan','Test plan','test-net')"
            )
            conn.execute(
                "INSERT INTO members VALUES ('test-patient','Synthetic Test Patient','Test P.','1234',1,'test-plan','2026-01-01','2099-01-01')"
            )
        yield client, db, settings


def test_production_never_accepts_demographics_and_requires_human_review(production):
    client, db, settings = production
    call_id = client.post("/calls", json={"room": "review-me"}).json()["call_id"]
    url = f"/calls/{call_id}/verify"
    for _ in range(4):
        response = client.post(url, json={"member_digits": "1234", "birth_month": 1})
        assert response.json()["error"] == "HUMAN_VERIFICATION_REQUIRED"
        assert "member" not in response.json()
    headers = {"Authorization": "Bearer review-secret-at-least-32-characters"}
    review = {
        "policy": settings.identity_policy,
        "reference": "case_test_0001",
        "outcome": "verified",
        "member_id": "test-patient",
    }
    assert (
        client.post(
            f"/identity/calls/{call_id}/review",
            json={**review, "policy": "unapproved"},
            headers=headers,
        ).status_code
        == 403
    )
    assert client.post(
        f"/identity/calls/{call_id}/review", json=review, headers=headers
    ).json() == {"status": "verified"}
    assert (
        client.post(
            f"/identity/calls/{call_id}/review", json=review, headers=headers
        ).status_code
        == 200
    )
    assert client.post(url, json={}).json()["member"]["name"] == "Test P."
    assert (
        client.post(
            f"/identity/calls/{call_id}/review",
            json={**review, "member_id": "another-patient"},
            headers=headers,
        ).status_code
        == 409
    )
    with db.snapshot() as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM identity_reviews").fetchone()[0] == 1


def test_three_human_review_failures_lock_even_after_restart(production):
    client, db, settings = production
    call_id = client.post("/calls", json={"room": "fail-review"}).json()["call_id"]
    headers = {"Authorization": "Bearer review-secret-at-least-32-characters"}
    for index in range(3):
        response = client.post(
            f"/identity/calls/{call_id}/review",
            json={
                "policy": settings.identity_policy,
                "reference": f"review_fail_{index}",
                "outcome": "failed",
            },
            headers=headers,
        )
        assert response.json()["status"] == ("locked" if index == 2 else "unverified")
    with TestClient(
        create_app(database=Database(db.path, clock=db.clock), security=settings),
        base_url="https://backend.test",
    ) as restarted:
        response = restarted.post(
            f"/calls/{call_id}/verify",
            json={},
            headers={"X-Agent-Key": AGENT, "X-Call-Key": CALL_A},
        )
        assert response.json()["error"] == "LOCKED"
        assert (
            restarted.post(
                f"/identity/calls/{call_id}/review",
                json={
                    "policy": settings.identity_policy,
                    "reference": "review_retry_4",
                    "outcome": "verified",
                    "member_id": "test-patient",
                },
                headers=headers,
            ).status_code
            == 403
        )


def test_production_rejects_plaintext_transport_and_missing_policies(production):
    client, _db, settings = production
    assert client.get("http://backend.test/now").status_code == 403
    assert client.get("/docs").status_code == 404
    assert client.post("/admin/reset", json={}).status_code == 403
    with pytest.raises(ValueError):
        replace(settings, identity_policy="").validate()


def test_unverified_production_turns_never_store_identity_answers(production):
    client, db, _ = production
    call_id = client.post("/calls", json={"room": "private-turns"}).json()["call_id"]
    body = {
        "client_turn_id": "repeat",
        "role": "user",
        "text": "My verification code is 123456",
    }
    assert client.post(f"/calls/{call_id}/turn", json=body).status_code == 201
    assert client.post(f"/calls/{call_id}/turn", json=body).status_code == 200
    with db.snapshot() as conn:
        assert (
            conn.execute(
                "SELECT text FROM turns WHERE call_id=?", (call_id,)
            ).fetchone()[0]
            == "[identity pending]"
        )
