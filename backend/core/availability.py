import json
from datetime import date, timedelta

from .common import (
    EASTERN,
    TIMEZONE,
    check_provider,
    covered,
    event,
    get_call,
    get_member,
    instant,
    invalidate,
    require_coverage,
    slot_view,
    utc,
)
from .errors import DomainError

WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


def get_now(db):
    now = db.now()
    local = now.astimezone(EASTERN)
    return {
        "now": utc(now),
        "business_date": local.date().isoformat(),
        "business_time": local.isoformat(timespec="seconds"),
        "timezone": TIMEZONE,
        "speak": "",
    }


def resolve_dates(db, call_id, weekday, which):
    with db.snapshot() as conn:
        get_call(conn, call_id, verified=True)
    today = db.now().astimezone(EASTERN).date()
    if weekday in ("today", "tomorrow"):
        if which != "unspecified":
            raise DomainError("INVALID_REQUEST")
        days = [today + timedelta(days=weekday == "tomorrow")]
    else:
        first = today + timedelta(days=(WEEKDAYS.index(weekday) - today.weekday()) % 7)
        days = [first] if which == "this" else [first, first + timedelta(days=7)]
    days = [day for day in days if day <= today + timedelta(days=14)]
    if not days:
        raise DomainError("OUTSIDE_WINDOW")
    candidates = [
        {
            "date": day.isoformat(),
            "text": f"{day.strftime('%A, %B')} {day.day}, {day.year}",
        }
        for day in days
    ]
    clarify = len(candidates) > 1
    speak = (
        "Do you mean " + " or ".join(c["text"] for c in candidates) + "?"
        if clarify
        else candidates[0]["text"] + "."
    )
    return {"candidates": candidates, "needs_clarification": clarify, "speak": speak}


def availability(db, call_id, date_from, date_to, part_of_day):
    start_day, end_day = date.fromisoformat(date_from), date.fromisoformat(date_to)
    with db.transaction() as conn:
        call = get_call(conn, call_id, verified=True, mutable=True)
        member = get_member(conn, call)
        now = db.now()
        today = now.astimezone(EASTERN).date()
        require_coverage(member, today)
        if start_day > end_day:
            raise DomainError("INVALID_REQUEST")
        if start_day < today:
            raise DomainError("SLOT_IN_PAST")
        if end_day > today + timedelta(days=14):
            raise DomainError("OUTSIDE_WINDOW")
        if not call["selected_provider_id"]:
            raise DomainError("NOT_BOOKABLE")
        check_provider(conn, call, member, call["selected_provider_id"])
        if (
            start_day.isoformat() > member["coverage_end"]
            or end_day.isoformat() < member["coverage_start"]
        ):
            require_coverage(member, start_day)
        offered = []
        for slot in conn.execute(
            "SELECT * FROM slots WHERE provider_id=? AND state='open' ORDER BY starts_at,id",
            (call["selected_provider_id"],),
        ):
            start = instant(slot["starts_at"])
            local = start.astimezone(EASTERN)
            if not start_day <= local.date() <= end_day or start < now + timedelta(
                hours=2
            ):
                continue
            if (
                not covered(member, local.date())
                or slot["modality"] != "in_person"
                or slot["visit_type"] != "new_patient"
            ):
                continue
            if (part_of_day == "morning" and local.hour >= 12) or (
                part_of_day == "afternoon" and local.hour < 12
            ):
                continue
            # Existing member/provider interval occupancy is unavailable, even
            # when a slot row itself still says open.
            if conn.execute(
                "SELECT 1 FROM appointments WHERE (provider_id=? OR member_id=?) AND starts_at<? AND ends_at>?",
                (slot["provider_id"], member["id"], slot["ends_at"], slot["starts_at"]),
            ).fetchone():
                continue
            offered.append(slot_view(slot))
            if len(offered) == 2:
                break
        invalidate(conn, call, clear_offers=True)
        query = {"date_from": date_from, "date_to": date_to, "part_of_day": part_of_day}
        version = call["request_version"] + 1
        conn.execute(
            "UPDATE calls SET request_version=?,availability_query_json=?,offered_slots_json=? WHERE id=?",
            (version, json.dumps(query), json.dumps(offered), call_id),
        )
        event(conn, call_id, "availability_offered", now)
        if not offered:
            raise DomainError("NO_AVAILABILITY", persist=True)
        return {
            "slots": offered,
            "request_version": version,
            "speak": "I can offer "
            + " or ".join(s["text"] for s in offered)
            + ". Which works for you?",
        }
