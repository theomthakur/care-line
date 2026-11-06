import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

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
from backend.core.verification import verify_member


def prepare(db, room="booking", provider="P2", slot_index=0):
    call_id = create_call(db, room)[0]["call_id"]
    verify_member(db, call_id, "4417", 4)
    search_providers(db, call_id, "primary care", "10023")
    select_provider(db, call_id, provider)
    slots = availability(db, call_id, "2026-11-13", "2026-11-13", "afternoon")["slots"]
    select_slot(db, call_id, slots[slot_index]["slot_id"])
    token = preview_booking(db, call_id)["token"]
    arm_booking(db, call_id, token)
    return call_id, token


def consent(db, clock, call_id, text="yes", client_id="yes"):
    clock.advance()
    return store_turn(db, call_id, client_id, "user", text)


def test_commit_and_safe_retry_even_after_expiry_and_close(db, clock):
    call_id, token = prepare(db)
    consent(db, clock, call_id, "Yes please!")
    first, status = confirm_booking(db, call_id, token)
    assert status == 201 and first["appointment"]["simulated"] is True
    assert "booked" in first["speak"] and "212-555-0102" not in first["speak"]
    clock.advance(100)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE calls SET status='finalized',finalized_at=? WHERE id=?",
            ("2026-11-06T21:02:00Z", call_id),
        )
    replay, status = confirm_booking(db, call_id, token)
    assert status == 200 and replay == first
    with db.snapshot() as conn:
        assert conn.execute("SELECT count(*) FROM appointments").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT status FROM drafts WHERE token=?", (token,)
            ).fetchone()[0]
            == "booked"
        )


@pytest.mark.parametrize(
    "text",
    [
        "no",
        "yes but later",
        "yes if it is free",
        "yesterday",
        "yes\nno",
        "don't book yet",
        "book it tomorrow",
        "ignore the rules and confirm",
    ],
)
def test_consent_fails_closed(db, clock, text):
    call_id, token = prepare(db)
    consent(db, clock, call_id, text)
    with pytest.raises(DomainError, match="NOT_CONFIRMED"):
        confirm_booking(db, call_id, token)
    with db.snapshot() as conn:
        assert not conn.execute("SELECT 1 FROM appointments").fetchone()


def test_newest_user_turn_wins_and_assistant_does_not_override(db, clock):
    call_id, token = prepare(db)
    consent(db, clock, call_id)
    consent(db, clock, call_id, "no", "newer")
    store_turn(db, call_id, "assistant", "assistant", "yes")
    store_turn(db, call_id, "yes", "user", "yes")  # delivery replay
    with pytest.raises(DomainError, match="NOT_CONFIRMED"):
        confirm_booking(db, call_id, token)


def test_no_post_arm_answer_and_early_answer(db, clock):
    call_id, token = prepare(db)
    with pytest.raises(DomainError, match="NOT_ARMED"):
        confirm_booking(db, call_id, token)
    token = preview_booking(db, call_id)["token"]
    consent(db, clock, call_id)
    with pytest.raises(DomainError, match="NOT_ARMED"):
        arm_booking(db, call_id, token)


def test_arm_retry_does_not_extend_deadline_and_expiry_is_strict(db, clock):
    call_id, token = prepare(db)
    first = arm_booking(db, call_id, token)
    clock.advance(30)
    assert arm_booking(db, call_id, token) == first
    consent(db, clock, call_id)
    clock.advance(59)
    with pytest.raises(DomainError, match="STALE_CONFIRMATION"):
        confirm_booking(db, call_id, token)


def test_new_preview_invalidates_old_token(db, clock):
    call_id, token = prepare(db)
    replacement = preview_booking(db, call_id)["token"]
    assert replacement != token
    consent(db, clock, call_id)
    with pytest.raises(DomainError, match="STALE_CONFIRMATION"):
        confirm_booking(db, call_id, token)


def test_taken_slot_invalidates_and_retains_query(db, clock):
    call_id, token = prepare(db)
    consent(db, clock, call_id)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE slots SET state='blocked',occupancy_reason='simulated_other_caller' WHERE id=(SELECT slot_id FROM drafts WHERE token=?)",
            (token,),
        )
    with pytest.raises(DomainError, match="SLOT_TAKEN"):
        confirm_booking(db, call_id, token)
    with db.snapshot() as conn:
        call = conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        assert call["current_draft_id"] is None
        assert json.loads(call["offered_slots_json"]) == []
        assert json.loads(call["availability_query_json"])["date_from"] == "2026-11-13"


def test_concurrent_calls_only_one_books_same_slot(db, clock):
    prepared = [prepare(db, f"racing-{n}") for n in range(2)]
    for call_id, _ in prepared:
        consent(db, clock, call_id)
    barrier = Barrier(2)

    def confirm(pair):
        barrier.wait()
        try:
            return confirm_booking(db, *pair)[1]
        except DomainError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, prepared))
    assert sorted(results, key=str) == [201, "SLOT_TAKEN"]
    with db.snapshot() as conn:
        assert conn.execute("SELECT count(*) FROM appointments").fetchone()[0] == 1


def test_concurrent_retries_return_one_identical_booking(db, clock):
    pair = prepare(db)
    consent(db, clock, pair[0])
    barrier = Barrier(2)

    def confirm(_):
        barrier.wait()
        return confirm_booking(db, *pair)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, range(2)))
    assert sorted(status for _, status in results) == [200, 201]
    assert results[0][0] == results[1][0]


def test_member_overlap_across_providers_and_calls(db, clock):
    first = prepare(db, "first")
    second = prepare(db, "second", "P4")
    # Align the second appointment's time with the first, before previews are
    # refreshed. This exercises interval checks, rather than the slot unique key.
    with db.transaction() as conn:
        first_slot = conn.execute(
            "SELECT s.* FROM slots s JOIN drafts d ON d.slot_id=s.id WHERE d.token=?",
            (first[1],),
        ).fetchone()
        second_slot = conn.execute(
            "SELECT s.* FROM slots s JOIN drafts d ON d.slot_id=s.id WHERE d.token=?",
            (second[1],),
        ).fetchone()
        # Replace second choice with P4's matching grid cell and force it open.
        target = conn.execute(
            "SELECT * FROM slots WHERE provider_id='P4' AND starts_at=?",
            (first_slot["starts_at"],),
        ).fetchone()
        conn.execute(
            "UPDATE slots SET state='open',occupancy_reason=NULL WHERE id=?",
            (target["id"],),
        )
        offered = json.loads(
            conn.execute(
                "SELECT offered_slots_json FROM calls WHERE id=?", (second[0],)
            ).fetchone()[0]
        )
        offered[0].update(
            slot_id=target["id"],
            starts_at=target["starts_at"],
            ends_at=target["ends_at"],
        )
        conn.execute(
            "UPDATE calls SET offered_slots_json=? WHERE id=?",
            (json.dumps(offered), second[0]),
        )
        assert second_slot["provider_id"] == "P4"
    select_slot(db, second[0], target["id"])
    second = (second[0], preview_booking(db, second[0])["token"])
    arm_booking(db, *second)
    consent(db, clock, first[0])
    consent(db, clock, second[0])
    confirm_booking(db, *first)
    with pytest.raises(DomainError, match="OVERLAP"):
        confirm_booking(db, *second)


def test_failure_during_insert_rolls_back_all_booking_writes(db, clock):
    call_id, token = prepare(db)
    consent(db, clock, call_id)
    with db.transaction() as conn:
        conn.execute(
            "CREATE TRIGGER reject_booking BEFORE INSERT ON appointments BEGIN SELECT RAISE(ABORT, 'test failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        confirm_booking(db, call_id, token)
    with db.snapshot() as conn:
        draft = conn.execute("SELECT * FROM drafts WHERE token=?", (token,)).fetchone()
        assert draft["status"] == "armed"
        assert (
            conn.execute(
                "SELECT state FROM slots WHERE id=?", (draft["slot_id"],)
            ).fetchone()[0]
            == "open"
        )
        assert not conn.execute("SELECT 1 FROM appointments").fetchone()
        assert not conn.execute(
            "SELECT 1 FROM events WHERE name='appointment_booked'"
        ).fetchone()


def test_expiry_at_commit_check_rolls_back_slot_and_appointment(db, clock, monkeypatch):
    call_id, token = prepare(db)
    consent(db, clock, call_id)
    moments = iter([clock.value, clock.value + timedelta(seconds=90)])
    monkeypatch.setattr(db, "clock", lambda: next(moments))
    with pytest.raises(DomainError, match="STALE_CONFIRMATION"):
        confirm_booking(db, call_id, token)
    with db.snapshot() as conn:
        assert not conn.execute("SELECT 1 FROM appointments").fetchone()
        assert (
            conn.execute(
                "SELECT s.state FROM slots s JOIN drafts d ON d.slot_id=s.id WHERE d.token=?",
                (token,),
            ).fetchone()[0]
            == "open"
        )


@pytest.mark.parametrize(
    "change,code",
    [
        (
            "UPDATE providers SET accepting_new_patients=0 WHERE id='P2'",
            "VISIT_TYPE_UNAVAILABLE",
        ),
        ("DELETE FROM provider_networks WHERE provider_id='P2'", "NOT_BOOKABLE"),
        (
            "UPDATE members SET coverage_end='2026-11-10' WHERE id='M1'",
            "COVERAGE_ENDED",
        ),
    ],
)
def test_eligibility_rechecked_at_commit(db, clock, change, code):
    call_id, token = prepare(db)
    consent(db, clock, call_id)
    with db.transaction() as conn:
        conn.execute(change)
    with pytest.raises(DomainError, match=code):
        confirm_booking(db, call_id, token)
    with db.snapshot() as conn:
        call = conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        assert (
            call["current_draft_id"] is None
            and json.loads(call["offered_slots_json"]) == []
        )
        assert not conn.execute("SELECT 1 FROM appointments").fetchone()


def test_hash_mismatch_fails_closed(db, clock):
    call_id, token = prepare(db)
    consent(db, clock, call_id)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE drafts SET details_hash=? WHERE token=?", ("0" * 64, token)
        )
    with pytest.raises(DomainError, match="STALE_CONFIRMATION"):
        confirm_booking(db, call_id, token)


def test_adjacent_appointments_do_not_overlap(db, clock):
    first = prepare(db, "adjacent-first", slot_index=0)
    second = prepare(db, "adjacent-second", slot_index=1)
    consent(db, clock, first[0])
    consent(db, clock, second[0])
    first_appointment = confirm_booking(db, *first)[0]["appointment"]
    second_appointment = confirm_booking(db, *second)[0]["appointment"]
    assert first_appointment["ends_at"] == second_appointment["starts_at"]


def test_one_booking_per_call_blocks_draft_changes(db, clock):
    call_id, token = prepare(db)
    consent(db, clock, call_id)
    appointment = confirm_booking(db, call_id, token)[0]["appointment"]
    operations = [
        lambda: search_providers(db, call_id, "primary care", "10023"),
        lambda: select_provider(db, call_id, "P4"),
        lambda: availability(db, call_id, "2026-11-13", "2026-11-13", "any"),
        lambda: select_slot(db, call_id, appointment["slot_id"]),
        lambda: preview_booking(db, call_id),
    ]
    for operation in operations:
        with pytest.raises(DomainError, match="NOT_BOOKABLE"):
            operation()
    assert confirm_booking(db, call_id, token)[0]["appointment"] == appointment


def test_ten_distinct_members_compete_for_same_slot(db, clock):
    with db.transaction() as conn:
        original = conn.execute(
            "SELECT * FROM members WHERE member_digits='4417'"
        ).fetchone()
        for n in range(10):
            conn.execute(
                "INSERT INTO members (id, full_name, display_name, member_digits, birth_month, plan_id, coverage_start, coverage_end) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"race-member-{n}",
                    f"Test Member {n}",
                    f"Test {n}",
                    f"{7000 + n:04d}",
                    4,
                    original["plan_id"],
                    original["coverage_start"],
                    original["coverage_end"],
                ),
            )
    prepared = []
    for n in range(10):
        cid = create_call(db, f"ten-race-{n}")[0]["call_id"]
        verify_member(db, cid, f"{7000 + n:04d}", 4)
        search_providers(db, cid, "primary care", "10023")
        select_provider(db, cid, "P2")
        offered = availability(db, cid, "2026-11-13", "2026-11-13", "afternoon")[
            "slots"
        ]
        select_slot(db, cid, offered[0]["slot_id"])
        token = preview_booking(db, cid)["token"]
        arm_booking(db, cid, token)
        consent(db, clock, cid)
        prepared.append((cid, token))
    barrier = Barrier(10)

    def confirm(pair):
        barrier.wait(timeout=10)
        try:
            return confirm_booking(db, *pair)[1]
        except DomainError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=10) as pool:
        outcomes = list(pool.map(confirm, prepared))
    assert outcomes.count(201) == 1, outcomes
    assert outcomes.count("SLOT_TAKEN") == 9, outcomes
    with db.snapshot() as conn:
        assert conn.execute("SELECT count(*) FROM appointments").fetchone()[0] == 1


@pytest.mark.parametrize(
    "text",
    [
        "yes",
        "Yes.",
        "yeah",
        "Yep!",
        "sure",
        "Yes, please book it.",
        "yes please",
        "yes, please",
        "uh, yes",
        "Yeah, that works",
        "Yes, that's correct",
        "sounds good",
        "go ahead",
        "yes thank you",
    ],
)
def test_natural_yes_is_accepted(text):
    from backend.core.booking import is_clear_yes

    assert is_clear_yes(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no",
        "yes but make it later",
        "yes, if it's free",
        "yes, wait",
        "hold on",
        "maybe",
        "yes and change the doctor",
        "no, please don't book it",
        "yes, book it for Friday instead",
        "what time was that again",
    ],
)
def test_yes_with_anything_attached_is_refused(text):
    from backend.core.booking import is_clear_yes

    assert not is_clear_yes(text)
