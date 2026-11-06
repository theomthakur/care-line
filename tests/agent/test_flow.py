"""The tools' logic against the stand-in backend. No LiveKit, no network."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend_client import BackendUnavailableError
from fake_backend import FakeBackend, is_clear_yes
from flow import Flow

ET = ZoneInfo("America/New_York")
MONDAY_NOON = datetime(2026, 11, 9, 12, 0, tzinfo=ET)  # slots exist Wed to Fri


class Handle:
    def __init__(self, interrupted: bool = False) -> None:
        self.interrupted = interrupted

    async def wait_for_playout(self) -> None:
        return None


def says(interrupted: bool = False):
    spoken: list[str] = []

    def say(text: str) -> Handle:
        spoken.append(text)
        return Handle(interrupted)

    say.spoken = spoken  # type: ignore[attr-defined]
    return say


async def booked_flow(be: FakeBackend) -> Flow:
    f = Flow(be)
    await f.start("room-1")
    await f.verify("four four one seven", "April")
    await f.find_providers("primary care", "10023")
    out = await f.find_slots("P2", "Friday", "afternoon")
    assert "S-P2-1113-1430" in out
    return f


@pytest.fixture
def be() -> FakeBackend:
    return FakeBackend(now=MONDAY_NOON)


async def test_happy_path_books_once_after_a_read_back_and_a_later_yes(
    be: FakeBackend,
) -> None:
    f = await booked_flow(be)
    say = says()
    assert await f.prepare("S-P2-1113-1430", say) is None
    assert "Dr. Omar Haddad" in say.spoken[0] and "Shall I book it?" in say.spoken[0]
    await f.record_user_turn("Yes")
    out = await f.confirm()
    assert (
        "confirmation number is M G A P T 4 8 2 1" in out
        and be.appointments[0]["start"].hour == 14
    )
    assert be.appointments[0]["confirmation"] == "MG-APT-4821"
    again = (
        await f.confirm()
    )  # a repeat returns the same confirmation, never a second booking
    assert "M G A P T 4 8 2 1" in again and len(be.appointments) == 1


async def test_a_yes_spoken_before_the_read_back_finished_never_books(
    be: FakeBackend,
) -> None:
    f = await booked_flow(be)
    await f.record_user_turn("Yes")  # said early, before arming
    await f.prepare("S-P2-1113-1430", says())
    out = await f.confirm()  # no user turn since the arming
    assert "I need a yes" in out and not be.appointments


async def test_an_interrupted_read_back_is_not_armed(be: FakeBackend) -> None:
    f = await booked_flow(be)
    out = await f.prepare("S-P2-1113-1430", says(interrupted=True))
    assert out is not None and "NOT ARMED" in out
    await f.record_user_turn("Yes")
    assert "NOT ARMED" in await f.confirm() and not be.appointments


@pytest.mark.parametrize(
    "reply",
    ["Yes, but make it later", "hold on", "no", "yes if it is free", "Actually, wait"],
)
async def test_anything_but_a_clear_yes_books_nothing(
    be: FakeBackend, reply: str
) -> None:
    f = await booked_flow(be)
    await f.prepare("S-P2-1113-1430", says())
    await f.record_user_turn(reply)
    out = await f.confirm()
    assert "Nothing is booked" in out or "nothing is booked" in out
    assert not be.appointments


async def test_an_older_yes_followed_by_a_newer_no_books_nothing(
    be: FakeBackend,
) -> None:
    f = await booked_flow(be)
    await f.prepare("S-P2-1113-1430", says())
    await f.record_user_turn("Yes")
    await f.record_user_turn("Wait, no")
    await f.confirm()
    assert not be.appointments


async def test_failed_new_turn_closes_confirmation(be: FakeBackend) -> None:
    f = await booked_flow(be)
    await f.prepare("S-P2-1113-1430", says())
    await f.record_user_turn("Yes")

    async def failed_turn(*_args: object) -> dict:
        raise BackendUnavailableError("connection failed")

    be.turn = failed_turn  # type: ignore[method-assign]
    with pytest.raises(BackendUnavailableError):
        await f.record_user_turn("No, do not book")
    assert "NOT ARMED" in await f.confirm()
    assert not be.appointments


async def test_selects_the_doctor_the_caller_chose(be: FakeBackend) -> None:
    f = Flow(be)
    await f.start("room-choice")
    await f.verify("4417", "April")
    await f.find_providers("primary care", "10023")
    await f.find_slots("P4", "Wednesday", "afternoon")
    assert be.calls[f.call_id]["selected"] == "P4"


async def test_the_slot_taken_during_the_read_back_offers_new_times(
    be: FakeBackend,
) -> None:
    f = await booked_flow(be)
    await f.prepare("S-P2-1113-1430", says())
    be.take_slot("S-P2-1113-1430")  # the demo button
    await f.record_user_turn("Yes")
    out = await f.confirm()
    assert "just taken" in out and "Nothing is booked" in out
    assert "S-P2-1113-1500" in out and "S-P2-1113-1430" not in out.split("Slot ids")[-1]
    assert not be.appointments


async def test_changing_the_time_after_the_read_back_voids_the_old_yes(
    be: FakeBackend,
) -> None:
    f = await booked_flow(be)
    await f.prepare("S-P2-1113-1430", says())
    await f.prepare("S-P2-1113-1500", says())  # a new read-back for the new time
    await f.record_user_turn("Yes")
    await f.confirm()
    assert (
        len(be.appointments) == 1
        and be.appointments[0]["start"].minute == 0
        and be.appointments[0]["start"].hour == 15
    )


async def test_an_outage_at_confirm_never_claims_a_booking(be: FakeBackend) -> None:
    f = await booked_flow(be)
    await f.prepare("S-P2-1113-1430", says())
    await f.record_user_turn("Yes")

    async def boom(*_: object) -> dict:
        raise BackendUnavailableError("down")

    be.confirm = boom  # type: ignore[method-assign]
    be.appointment = boom  # type: ignore[method-assign]
    out = await f.confirm()
    assert "UNKNOWN OUTCOME" in out and "do not say it is booked" in out
    assert f.booked is None


async def test_an_outage_after_the_write_is_found_by_checking_the_stored_appointment(
    be: FakeBackend,
) -> None:
    f = await booked_flow(be)
    await f.prepare("S-P2-1113-1430", says())
    await f.record_user_turn("Yes")
    real_confirm = be.confirm

    async def write_then_drop(call_id: str, token: str) -> dict:
        await real_confirm(call_id, token)
        raise BackendUnavailableError("timeout after the write")

    be.confirm = write_then_drop  # type: ignore[method-assign]
    out = await f.confirm()
    assert "did go through" in out and len(be.appointments) == 1


async def test_two_failures_in_a_row_tell_the_agent_to_wrap_up(be: FakeBackend) -> None:
    f = Flow(be)
    await f.start("r")

    async def boom(*_: object) -> dict:
        raise BackendUnavailableError("down")

    be.verify = boom  # type: ignore[method-assign]
    first = await f.verify("4417", "April")
    second = await f.verify("4417", "April")
    assert "try once more" in first and "call back" in second


async def test_the_excluded_doctor_is_never_offered_but_the_reason_is_noted(
    be: FakeBackend,
) -> None:
    f = Flow(be)
    await f.start("r")
    await f.verify("4417", "April")
    out = await f.find_providers("primary care", "10019")
    assert "P3" not in f.provider_options and "P1" not in f.provider_options
    assert "out of network" in out and "not accepting new patients" in out


async def test_unverified_callers_get_no_providers(be: FakeBackend) -> None:
    f = Flow(be)
    await f.start("r")
    out = await f.find_providers("primary care", "10023")
    assert "verify" in out.lower()


async def test_three_wrong_tries_lock_verification(be: FakeBackend) -> None:
    f = Flow(be)
    await f.start("r")
    for _ in range(3):
        await f.verify("0000", "May")
    out = await f.verify("4417", "April")
    assert "can't verify" in out and not f.verified


async def test_a_time_that_was_never_offered_cannot_be_prepared(
    be: FakeBackend,
) -> None:
    f = await booked_flow(be)
    out = await f.prepare("S-P4-1111-1300", says())
    assert out is not None and "wasn't one I offered" in out


async def test_a_bare_weekday_late_in_the_week_asks_which_date() -> None:
    be = FakeBackend(now=datetime(2026, 11, 13, 9, 0, tzinfo=ET))  # a Friday
    f = Flow(be)
    await f.start("r")
    await f.verify("4417", "April")
    await f.find_providers("primary care", "10023")
    out = await f.find_slots("P2", "Friday")
    assert "Do you mean" in out


@pytest.mark.parametrize(
    "text",
    [
        "yes",
        "Yes.",
        "yeah",
        "Yes please",
        "sure",
        "go ahead",
        "book it",
        "Yes, please book it.",
        "yes, go ahead",
        "Yes, that's right",
        "yes that works, thanks",
    ],
)
def test_clear_yes(text: str) -> None:
    assert is_clear_yes(text)


@pytest.mark.parametrize(
    "text",
    [
        "yes but later",
        "no",
        "hold on",
        "yes, if it's free",
        "maybe",
        "yes and change it",
        "yes, please book it but later",
        "yes, book it for Friday instead",
        "yes please, wait",
        "no, please don't book it",
        "",
    ],
)
def test_not_a_clear_yes(text: str) -> None:
    assert not is_clear_yes(text)


async def test_unreadable_backend_answers_never_crash_or_book() -> None:
    be = FakeBackend()
    f = Flow(be)
    await f.start("r")
    await f.verify("4417", "April")
    await f.find_providers("primary care", "10023")

    async def ok_only(*a: object, **k: object) -> dict:
        return {"ok": True}

    be.confirm = ok_only  # type: ignore[method-assign]
    f.token, f.armed = "t", True
    out = await f.confirm()
    assert "UNKNOWN OUTCOME" in out and f.booked is None

    be.dates = lambda *a, **k: ok_only()  # type: ignore[method-assign]
    assert "Which day" in await f.find_slots("P2", "Thursday")

    be.providers = lambda *a, **k: ok_only()  # type: ignore[method-assign]
    assert "couldn't find" in await f.find_providers("primary care", "10023")


async def test_call_restarts_if_backend_was_down_at_pickup() -> None:
    f = Flow(FakeBackend())
    f.room = "r"  # start() failed earlier, so call_id is None
    await f.record_user_turn("hello")
    assert f.call_id


async def test_earliest_available_looks_across_schedule(be: FakeBackend) -> None:
    f = Flow(be)
    await f.start("earliest")
    await f.verify("4417", "April")
    await f.find_providers("primary care", "10019")
    answer = await f.find_slots("P2", "earliest available", "")
    assert "S-P2-1112-0930" in answer
    assert "Thursday" in answer


async def test_no_tomorrow_slot_offers_next_actual_availability(
    be: FakeBackend,
) -> None:
    f = Flow(be)
    await f.start("tomorrow")
    await f.verify("4417", "April")
    await f.find_providers("primary care", "10019")
    answer = await f.find_slots("P2", "tomorrow", "")
    assert "S-P2-1112-0930" in answer
    assert "Thursday" in answer
