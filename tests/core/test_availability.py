from datetime import datetime, timezone

import pytest

from backend.core.availability import availability, get_now, resolve_dates
from backend.core.calls import create_call
from backend.core.errors import DomainError
from backend.core.providers import search_providers, select_provider
from backend.core.seed import seed
from backend.core.verification import verify_member


def selected(db, room="dates"):
    call_id = create_call(db, room)[0]["call_id"]
    verify_member(db, call_id, "4417", 4)
    search_providers(db, call_id, "primary care", "10023")
    select_provider(db, call_id, "P2")
    return call_id


def test_ambiguous_friday_returns_two_backend_dates(db):
    call_id = selected(db)
    result = resolve_dates(db, call_id, "friday", "next")
    assert result["needs_clarification"] is True
    assert [c["date"] for c in result["candidates"]] == ["2026-11-06", "2026-11-13"]
    assert resolve_dates(db, call_id, "friday", "this")["needs_clarification"] is False
    assert (
        resolve_dates(db, call_id, "tomorrow", "unspecified")["candidates"][0]["date"]
        == "2026-11-07"
    )


def test_forced_demo_slots_and_two_option_limit(db):
    call_id = selected(db)
    result = availability(db, call_id, "2026-11-13", "2026-11-13", "afternoon")
    assert [s["starts_at"] for s in result["slots"]] == [
        "2026-11-13T19:30:00Z",
        "2026-11-13T20:00:00Z",
    ]
    assert "2:30 PM Eastern time" in result["slots"][0]["text"]
    thursday = availability(db, call_id, "2026-11-12", "2026-11-12", "morning")
    assert [s["starts_at"] for s in thursday["slots"]] == [
        "2026-11-12T14:30:00Z",
        "2026-11-12T15:30:00Z",
    ]


@pytest.mark.parametrize(
    "start,end,code",
    [
        ("2026-11-05", "2026-11-06", "SLOT_IN_PAST"),
        ("2026-11-06", "2026-11-21", "OUTSIDE_WINDOW"),
        ("2026-11-12", "2026-11-11", "INVALID_REQUEST"),
        ("2026-11-07", "2026-11-08", "NO_AVAILABILITY"),
    ],
)
def test_invalid_ranges_and_weekends(db, start, end, code):
    with pytest.raises(DomainError, match=code):
        availability(db, selected(db), start, end, "any")


def test_eastern_clock_crosses_utc_midnight_and_dst(db, clock):
    clock.value = datetime(2026, 11, 7, 1, tzinfo=timezone.utc)
    assert get_now(db)["business_date"] == "2026-11-06"
    assert get_now(db)["business_time"].endswith("-05:00")
    clock.value = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    seed(db, demo_date=clock().date())
    assert get_now(db)["business_time"].endswith("-04:00")
    call_id = selected(db)
    offered = availability(db, call_id, "2026-11-02", "2026-11-02", "any")["slots"]
    assert all(
        s["starts_at"][11:13] >= "14" for s in offered
    )  # 9 AM is 14 UTC after DST


def test_exactly_two_hours_allowed_and_coverage_by_visit_date(db, clock):
    call_id = selected(db)
    clock.value = datetime(2026, 11, 13, 17, 30, tzinfo=timezone.utc)
    offered = availability(db, call_id, "2026-11-13", "2026-11-13", "afternoon")[
        "slots"
    ]
    assert offered[0]["starts_at"] == "2026-11-13T19:30:00Z"
    clock.advance(1)
    offered = availability(db, call_id, "2026-11-13", "2026-11-13", "afternoon")[
        "slots"
    ]
    assert offered[0]["starts_at"] == "2026-11-13T20:00:00Z"
    with db.transaction() as conn:
        conn.execute("UPDATE members SET coverage_end='2026-11-13' WHERE id='M1'")
    with pytest.raises(DomainError, match="COVERAGE_ENDED"):
        availability(db, call_id, "2026-11-16", "2026-11-16", "any")
    assert availability(db, call_id, "2026-11-13", "2026-11-16", "any")["slots"][0][
        "starts_at"
    ].startswith("2026-11-13")
