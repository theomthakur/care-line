import pytest

from backend.core.calls import create_call
from backend.core.errors import DomainError
from backend.core.verification import normalize_digits, verify_member


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("4417", "4417"),
        ("four-four one seven", "4417"),
        ("4 4 1 7", "4417"),
        ("oh zero one two", "0012"),
    ],
)
def test_normalize_digits(raw, expected):
    assert normalize_digits(raw) == expected


def test_three_failures_lock_and_create_exactly_one_task(db):
    call_id = create_call(db, "locked")[0]["call_id"]
    for remaining in (2, 1, 0, 0):
        with pytest.raises(DomainError) as error:
            verify_member(db, call_id, "0000", 4)
        assert error.value.code == (
            "LOCKED" if remaining == 0 else "VERIFICATION_FAILED"
        )
        assert error.value.body["attempts_remaining"] == remaining
    with db.snapshot() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM tasks WHERE call_id=?", (call_id,)
            ).fetchone()[0]
            == 1
        )
        call = conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        assert call["verification_attempts"] == 3 and call["member_id"] is None


def test_ambiguous_stt_is_not_guessed_or_counted(db):
    call_id = create_call(db, "uncertain")[0]["call_id"]
    with pytest.raises(DomainError, match="INVALID_REQUEST"):
        verify_member(db, call_id, "for for one seven", 4)
    with db.snapshot() as conn:
        assert (
            conn.execute(
                "SELECT verification_attempts FROM calls WHERE id=?", (call_id,)
            ).fetchone()[0]
            == 0
        )


def test_reverification_cannot_change_identity(db):
    call_id = create_call(db, "identity")[0]["call_id"]
    first = verify_member(db, call_id, "4417", 4)
    assert verify_member(db, call_id, "2261", 6)["member"] == first["member"]


def test_expired_member_can_verify_identity(db):
    call_id = create_call(db, "expired")[0]["call_id"]
    assert verify_member(db, call_id, "8832", 9)["member"]["active"] is False


def test_a_member_can_be_on_only_one_live_call(db, clock):
    db.one_call_per_member = True
    first = create_call(db, "room-one")[0]["call_id"]
    verify_member(db, first, "4417", 4)
    second = create_call(db, "room-two")[0]["call_id"]
    with pytest.raises(DomainError) as busy:
        verify_member(db, second, "4417", 4)
    assert busy.value.code == "MEMBER_IN_USE"
    # Not a failed attempt: the second caller is not locked out.
    # Once the first call has gone quiet for five minutes it no longer blocks.
    clock.advance(360)
    assert verify_member(db, second, "4417", 4)["status"] == "verified"
    # A different member is never blocked.
    third = create_call(db, "room-three")[0]["call_id"]
    assert verify_member(db, third, "2261", 6)["status"] == "verified"
