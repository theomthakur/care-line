"""Specialist booking: referral policy is enforced by the backend at every step."""

from datetime import date

import pytest

from backend.core.availability import availability
from backend.core.booking import (
    arm_booking,
    confirm_booking,
    preview_booking,
    select_slot,
)
from backend.core.calls import create_call, store_turn
from backend.core.errors import DomainError
from backend.core.providers import search_providers, select_provider
from backend.core.seed import seed
from backend.core.verification import verify_member

MEMBERS = {
    "maya": ("4417", 4),
    "riley": ("2261", 6),
    "tessa": ("7734", 2),
    "jordan": ("6652", 11),
}


@pytest.fixture
def journeys(db):
    seed(db, demo_date=date(2026, 11, 6), care_journeys=True)
    return db


def start(db, who):
    call_id = create_call(db, who)[0]["call_id"]
    verify_member(db, call_id, *MEMBERS[who])
    return call_id


def book(db, clock, call_id, provider, date_from, date_to):
    select_provider(db, call_id, provider)
    slot = availability(db, call_id, date_from, date_to, "")["slots"][0]
    select_slot(db, call_id, slot["slot_id"])
    preview = preview_booking(db, call_id)
    arm_booking(db, call_id, preview["token"])
    clock.advance()
    store_turn(db, call_id, "yes", "user", "yes")
    result, status = confirm_booking(db, call_id, preview["token"])
    assert status == 201
    return preview, slot, result


def test_gold_member_books_dermatology_without_referral(db, clock):
    call_id = start(db, "maya")
    found = search_providers(db, call_id, "dermatologist", "10023")
    assert [p["id"] for p in found["providers"]] == ["P8", "P5"]
    assert found["evidence"][0]["id"] == "GOLD-REF"
    assert found["referral"]["status"] == "not_required"
    assert found["speak"].startswith("Your plan doesn't need a referral")
    preview, _, result = book(db, clock, call_id, "P8", "2026-11-09", "2026-11-13")
    assert "new-patient dermatology visit" in preview["read_back"]
    with db.snapshot() as conn:
        row = conn.execute(
            "SELECT provider_id, referral_id FROM appointments WHERE call_id=?",
            (call_id,),
        ).fetchone()
    assert tuple(row) == ("P8", None)
    assert result["appointment"]["doctor"] == "Dr. Aaron Shah"


def test_basic_member_with_valid_referral_books_cardiology(journeys, clock):
    call_id = start(journeys, "riley")
    found = search_providers(journeys, call_id, "cardiology", "10023")
    assert [p["id"] for p in found["providers"]] == ["P6"]
    assert {e["id"]: e["reason"] for e in found["excluded"]} == {
        "P7": "out of network",
        "P9": "not accepting new patients",
    }
    assert found["referral"]["status"] == "valid"
    assert found["referral"]["referral"]["id"] == "REF-M2-CARD"
    assert found["evidence"][0]["id"] == "BASIC-REF"
    _, slot, _ = book(journeys, clock, call_id, "P6", "2026-11-09", "2026-11-20")
    assert slot["starts_at"][:10] <= "2026-11-13"
    with journeys.snapshot() as conn:
        assert (
            conn.execute(
                "SELECT referral_id FROM appointments WHERE call_id=?", (call_id,)
            ).fetchone()[0]
            == "REF-M2-CARD"
        )


def test_slots_after_referral_expiry_are_never_offered(journeys):
    call_id = start(journeys, "riley")
    search_providers(journeys, call_id, "cardiology", "10023")
    select_provider(journeys, call_id, "P6")
    with pytest.raises(DomainError, match="NO_AVAILABILITY"):
        availability(journeys, call_id, "2026-11-16", "2026-11-20", "")


@pytest.mark.parametrize(
    "who,specialty,status",
    [
        ("tessa", "cardiology", "missing"),
        ("jordan", "dermatology", "expired"),
        ("jordan", "cardiology", "revoked"),
    ],
)
def test_basic_member_without_valid_referral_is_refused(
    journeys, who, specialty, status
):
    call_id = start(journeys, who)
    with pytest.raises(DomainError) as refused:
        search_providers(journeys, call_id, specialty, "10023")
    assert refused.value.code == "REFERRAL_REQUIRED"
    assert refused.value.body["referral_status"] == status
    assert "follow-up" in refused.value.body["speak"]
    with journeys.snapshot() as conn:
        call = conn.execute(
            "SELECT specialty, providers_json, evidence_json FROM calls WHERE id=?",
            (call_id,),
        ).fetchone()
    # The refusal is saved with the plan passage so the console can show why.
    assert call["specialty"] == specialty and call["providers_json"] == "[]"
    assert "BASIC-REF" in call["evidence_json"]


def test_primary_care_doctor_cannot_be_picked_for_a_specialist_search(db):
    call_id = start(db, "maya")
    search_providers(db, call_id, "dermatology", "10023")
    with pytest.raises(DomainError, match="VISIT_TYPE_UNAVAILABLE"):
        select_provider(db, call_id, "P2")


def test_referral_revoked_before_yes_blocks_the_booking(journeys, clock):
    call_id = start(journeys, "riley")
    search_providers(journeys, call_id, "cardiology", "10023")
    select_provider(journeys, call_id, "P6")
    slot = availability(journeys, call_id, "2026-11-09", "2026-11-13", "")["slots"][0]
    select_slot(journeys, call_id, slot["slot_id"])
    token = preview_booking(journeys, call_id)["token"]
    arm_booking(journeys, call_id, token)
    with journeys.transaction() as conn:
        conn.execute("UPDATE referrals SET status='revoked' WHERE id='REF-M2-CARD'")
    clock.advance()
    store_turn(journeys, call_id, "yes", "user", "yes")
    with pytest.raises(DomainError, match="REFERRAL_REQUIRED"):
        confirm_booking(journeys, call_id, token)
    with journeys.snapshot() as conn:
        assert not conn.execute(
            "SELECT 1 FROM appointments WHERE call_id=?", (call_id,)
        ).fetchone()


def test_specialist_search_over_http_returns_referral_refusal(client, db):
    seed(db, demo_date=date(2026, 11, 6), care_journeys=True)
    call_id = client.post("/calls", json={"room": "tessa"}).json()["call_id"]
    client.post(
        f"/calls/{call_id}/verify", json={"member_digits": "7734", "birth_month": 2}
    )
    res = client.post(
        f"/calls/{call_id}/providers", json={"specialty": "cardiology", "zip": "10023"}
    )
    assert res.status_code == 403
    assert res.json()["error"] == "REFERRAL_REQUIRED"
    assert res.json()["referral_status"] == "missing"


def test_refusal_is_recorded_for_the_console(journeys):
    call_id = start(journeys, "tessa")
    with pytest.raises(DomainError, match="REFERRAL_REQUIRED"):
        search_providers(journeys, call_id, "cardiology", "10023")
    with journeys.snapshot() as conn:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM events WHERE call_id=? ORDER BY id", (call_id,)
            )
        ]
    assert names[-1] == "referral_required"
