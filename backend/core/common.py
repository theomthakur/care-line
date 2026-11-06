import json
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .errors import DomainError

EASTERN = ZoneInfo("America/New_York")
TIMEZONE = "America/New_York"


def utc(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def identifier(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def event(conn, call_id, name, now):
    conn.execute(
        "INSERT INTO events(call_id,name,created_at) VALUES (?,?,?)",
        (call_id, name, utc(now)),
    )


def get_call(conn, call_id, *, verified=False, live=True, mutable=False):
    call = conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
    if call is None:
        raise DomainError("CALL_NOT_FOUND")
    if verified and call["verification_status"] != "verified":
        raise DomainError("VERIFICATION_REQUIRED")
    if live and call["status"] != "live":
        raise DomainError("CALL_CLOSED")
    if (
        mutable
        and conn.execute(
            "SELECT 1 FROM appointments WHERE call_id=?", (call_id,)
        ).fetchone()
    ):
        raise DomainError("NOT_BOOKABLE")
    return call


def get_member(conn, call):
    return conn.execute(
        "SELECT m.*, p.name AS plan, p.network FROM members m JOIN plans p ON p.id=m.plan_id WHERE m.id=?",
        (call["member_id"],),
    ).fetchone()


def covered(member, day):
    return member["coverage_start"] <= day.isoformat() <= member["coverage_end"]


def require_coverage(member, day):
    if not covered(member, day):
        end = date.fromisoformat(member["coverage_end"])
        label = f"{end.strftime('%B')} {end.day}, {end.year}"
        raise DomainError(
            "COVERAGE_ENDED",
            f"Your coverage ends on {label}. I can't offer an appointment outside that coverage.",
        )


def member_view(member, now):
    return {
        "name": member["display_name"],
        "id_masked": "***" + member["member_digits"],
        "plan": member["plan"],
        "network": member["network"],
        "active": covered(member, now.astimezone(EASTERN).date()),
    }


def provider_view(provider):
    return {
        key: (bool(provider[key]) if key == "accepting_new_patients" else provider[key])
        for key in ("id", "name", "specialty", "zip", "phone", "accepting_new_patients")
    }


def spoken_time(value):
    local = instant(value).astimezone(EASTERN)
    return f"{local.strftime('%A, %B')} {local.day}, {local.year} at {local.strftime('%I:%M %p').lstrip('0')} Eastern time"


def slot_view(slot):
    return {
        "slot_id": slot["id"],
        "provider_id": slot["provider_id"],
        "starts_at": slot["starts_at"],
        "ends_at": slot["ends_at"],
        "timezone": TIMEZONE,
        "text": spoken_time(slot["starts_at"]),
    }


def invalidate(conn, call, *, clear_offers=False):
    conn.execute(
        "UPDATE drafts SET status='invalidated' WHERE call_id=? AND status NOT IN ('booked','invalidated')",
        (call["id"],),
    )
    conn.execute("UPDATE calls SET current_draft_id=NULL WHERE id=?", (call["id"],))
    if clear_offers:
        conn.execute(
            "UPDATE calls SET offered_slots_json='[]' WHERE id=?", (call["id"],)
        )


def check_provider(conn, call, member, provider_id):
    provider = conn.execute(
        "SELECT * FROM providers WHERE id=?", (provider_id,)
    ).fetchone()
    if provider is None:
        raise DomainError("UNKNOWN_PROVIDER")
    if not conn.execute(
        "SELECT 1 FROM provider_networks WHERE provider_id=? AND network=?",
        (provider_id, member["network"]),
    ).fetchone():
        raise DomainError("NOT_BOOKABLE")
    if (
        provider["specialty"] != "primary care"
        or not provider["accepting_new_patients"]
    ):
        raise DomainError(
            "VISIT_TYPE_UNAVAILABLE",
            "That office isn't accepting new-patient primary care visits.",
        )
    if provider_id not in {p["id"] for p in json.loads(call["providers_json"])}:
        raise DomainError("NOT_BOOKABLE")
    return provider


def check_slot(conn, call, member, slot_id, now):
    require_coverage(member, now.astimezone(EASTERN).date())
    check_provider(conn, call, member, call["selected_provider_id"])
    if slot_id not in {s["slot_id"] for s in json.loads(call["offered_slots_json"])}:
        raise DomainError("NOT_BOOKABLE")
    slot = conn.execute("SELECT * FROM slots WHERE id=?", (slot_id,)).fetchone()
    if slot is None or slot["provider_id"] != call["selected_provider_id"]:
        raise DomainError("NOT_BOOKABLE")
    if slot["visit_type"] != "new_patient" or slot["modality"] != "in_person":
        raise DomainError("VISIT_TYPE_UNAVAILABLE")
    start, end = instant(slot["starts_at"]), instant(slot["ends_at"])
    local = start.astimezone(EASTERN)
    if (
        end - start != timedelta(minutes=30)
        or local.minute not in (0, 30)
        or local.second
        or local.microsecond
        or local.weekday() >= 5
        or not 9 <= local.hour < 17
    ):
        raise DomainError("NOT_BOOKABLE")
    require_coverage(member, local.date())
    if start < now:
        raise DomainError("SLOT_IN_PAST")
    if start < now + timedelta(hours=2):
        raise DomainError("TOO_SOON")
    if local.date() > now.astimezone(EASTERN).date() + timedelta(days=14):
        raise DomainError("OUTSIDE_WINDOW")
    if slot["state"] != "open":
        raise DomainError("SLOT_TAKEN")
    return slot


def latest_user(conn, call_id):
    return conn.execute(
        "SELECT * FROM turns WHERE call_id=? AND role='user' ORDER BY seq DESC LIMIT 1",
        (call_id,),
    ).fetchone()
