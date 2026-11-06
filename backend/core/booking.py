"""Backend-owned consent and atomic appointment commits. No model decisions."""

import hashlib
import json
import re
import secrets
from datetime import timedelta

from .common import (
    TIMEZONE,
    check_slot,
    event,
    get_call,
    get_member,
    identifier,
    instant,
    invalidate,
    latest_user,
    slot_view,
    spoken_time,
    utc,
)
from .errors import DomainError

_YES_WORD = (
    r"(?:yes|yeah|yea|yep|yup|sure|ok|okay|correct|right|absolutely|definitely|"
    r"certainly|of course|that'?s right|that'?s correct|that works|sounds good|"
    r"that sounds good|perfect|go ahead|please do|do it|book it|confirm|confirmed|"
    r"i do|i confirm|let'?s do it|i'?d like that)"
)
# Only these confirming words may follow a yes. Anything else ("but later", "if it's
# free", "no", "wait") is not a clean yes and books nothing.
_YES_TAIL = (
    rf"(?:{_YES_WORD}|please|thanks|thank you|book that|please book it|please book that|"
    r"please go ahead|that'?s fine|that'?s good|sir|ma'?am)"
)
_YES = re.compile(
    rf"^(?:(?:uh|um|er|hmm|mm|well|so)[\s,]+)*{_YES_WORD}(?:[\s,]+{_YES_TAIL})*$"
)


def is_clear_yes(text):
    """A yes with nothing added. 'Yes, but later', 'hold on' and 'no' are not a yes."""
    t = " ".join(str(text).replace("\u2019", "'").lower().split())
    return bool(_YES.match(t.strip(" ,.!?;")))


DIGIT_WORDS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
]


def detail_hash(member_id, slot):
    details = [
        member_id,
        slot["provider_id"],
        slot["id"],
        slot["starts_at"],
        slot["ends_at"],
        slot["visit_type"],
        slot["modality"],
    ]
    return hashlib.sha256(
        json.dumps(details, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def select_slot(db, call_id, slot_id):
    with db.transaction() as conn:
        call = get_call(conn, call_id, verified=True, mutable=True)
        now = db.now()
        slot = check_slot(conn, call, get_member(conn, call), slot_id, now)
        revision = conn.execute(
            "SELECT COALESCE(MAX(revision),0)+1 FROM drafts WHERE call_id=?", (call_id,)
        ).fetchone()[0]
        invalidate(conn, call)
        draft_id = identifier("draft")
        conn.execute(
            "INSERT INTO drafts(id,call_id,member_id,provider_id,slot_id,revision,request_version,status,created_at) VALUES (?,?,?,?,?,?,?,'slot',?)",
            (
                draft_id,
                call_id,
                call["member_id"],
                slot["provider_id"],
                slot_id,
                revision,
                call["request_version"],
                utc(now),
            ),
        )
        conn.execute(
            "UPDATE calls SET current_draft_id=? WHERE id=?", (draft_id, call_id)
        )
        event(conn, call_id, "slot_selected", now)
        return {
            "slot": slot_view(slot),
            "revision": revision,
            "status": "slot",
            "speak": "Let me read that back to you.",
        }


def current_draft(conn, call, token=None):
    draft = conn.execute(
        "SELECT * FROM drafts WHERE id=? AND call_id=?",
        (call["current_draft_id"], call["id"]),
    ).fetchone()
    code = "STALE_CONFIRMATION" if token is not None else "NOT_BOOKABLE"
    if not draft or draft["status"] in ("invalidated", "booked"):
        raise DomainError(code)
    if token is not None and (draft["token"] != token or draft["status"] == "slot"):
        raise DomainError("STALE_CONFIRMATION")
    if (
        draft["member_id"] != call["member_id"]
        or draft["provider_id"] != call["selected_provider_id"]
        or draft["request_version"] != call["request_version"]
    ):
        raise DomainError(code)
    if token is not None:
        slot = conn.execute(
            "SELECT * FROM slots WHERE id=?", (draft["slot_id"],)
        ).fetchone()
        if slot is None or draft["details_hash"] != detail_hash(
            call["member_id"], slot
        ):
            raise DomainError("STALE_CONFIRMATION")
    return draft


def checked_draft_slot(conn, call, draft, now):
    try:
        return check_slot(conn, call, get_member(conn, call), draft["slot_id"], now)
    except DomainError as exc:
        invalidate(conn, call, clear_offers=True)
        event(conn, call["id"], "preview_invalidated", now)
        exc.persist = True
        raise


def preview_booking(db, call_id):
    with db.transaction() as conn:
        call = get_call(conn, call_id, verified=True, mutable=True)
        now = db.now()
        draft = current_draft(conn, call)
        slot = checked_draft_slot(conn, call, draft, now)
        member = get_member(conn, call)
        provider = conn.execute(
            "SELECT name FROM providers WHERE id=?", (slot["provider_id"],)
        ).fetchone()
        read_back = f"{member['display_name']}, this is a new-patient primary care visit, in person, with {provider['name']} on {spoken_time(slot['starts_at'])}. Would you like me to book it?"
        token = secrets.token_urlsafe(32)
        user = latest_user(conn, call_id)
        conn.execute(
            "UPDATE drafts SET status='preview',token=?,details_hash=?,read_back=?,preview_user_seq=?,armed_seq=NULL,armed_at=NULL,expires_at=NULL WHERE id=?",
            (
                token,
                detail_hash(member["id"], slot),
                read_back,
                user["seq"] if user else 0,
                draft["id"],
            ),
        )
        event(conn, call_id, "preview_created", now)
        return {
            "token": token,
            "revision": draft["revision"],
            "status": "preview",
            "read_back": read_back,
            "speak": "",
        }


def arm_booking(db, call_id, token):
    with db.transaction() as conn:
        call = get_call(conn, call_id, verified=True)
        draft = current_draft(conn, call, token)
        now = db.now()
        if draft["status"] == "armed":
            if now >= instant(draft["expires_at"]):
                raise DomainError("STALE_CONFIRMATION")
            return armed_view(draft)
        user = latest_user(conn, call_id)
        seq = user["seq"] if user else 0
        if seq != draft["preview_user_seq"]:
            raise DomainError("NOT_ARMED")
        checked_draft_slot(conn, call, draft, now)
        # Only the trusted adapter invokes this after exact, uninterrupted speech.
        conn.execute(
            "UPDATE drafts SET status='armed',armed_seq=?,armed_at=?,expires_at=? WHERE id=?",
            (seq, utc(now), utc(now + timedelta(seconds=90)), draft["id"]),
        )
        event(conn, call_id, "confirmation_armed", now)
        return armed_view(
            conn.execute("SELECT * FROM drafts WHERE id=?", (draft["id"],)).fetchone()
        )


def armed_view(draft):
    return {
        "status": "armed",
        "armed_seq": draft["armed_seq"],
        "armed_at": draft["armed_at"],
        "expires_at": draft["expires_at"],
        "speak": "Please say yes if you want me to book it.",
    }


def appointment_view(conn, appointment):
    provider = conn.execute(
        "SELECT name,phone FROM providers WHERE id=?", (appointment["provider_id"],)
    ).fetchone()
    return {
        "appointment_id": appointment["id"],
        "status": "booked",
        "confirmation": appointment["confirmation"],
        "provider_id": appointment["provider_id"],
        "slot_id": appointment["slot_id"],
        "doctor": provider["name"],
        "phone": provider["phone"],
        "starts_at": appointment["starts_at"],
        "ends_at": appointment["ends_at"],
        "timezone": TIMEZONE,
        "when": spoken_time(appointment["starts_at"]),
        "simulated": True,
    }


def say_digits(value):
    return " ".join(
        DIGIT_WORDS[int(char)] if char.isdigit() else char
        for char in value
        if char != "-"
    )


def confirmation_response(conn, appointment):
    result = appointment_view(conn, appointment)
    digits = say_digits(result["confirmation"].removeprefix("MG-APT-"))
    phone = ", ".join(say_digits(group) for group in result["phone"].split("-"))
    return {
        "appointment": result,
        "speak": f"Your appointment with {result['doctor']} is booked for {result['when']}. Your confirmation is M G, A P T, {digits}; the office number is {phone}.",
    }


def confirm_booking(db, call_id, token):
    with db.transaction() as conn:
        call = get_call(conn, call_id, verified=True, live=False)
        # Replay comes before finalization, expiry and changed eligibility checks.
        saved = conn.execute(
            "SELECT a.* FROM appointments a JOIN drafts d ON d.id=a.draft_id WHERE a.call_id=? AND d.call_id=? AND d.token=?",
            (call_id, call_id, token),
        ).fetchone()
        if saved:
            return confirmation_response(conn, saved), 200
        draft = current_draft(conn, call, token)
        if call["status"] != "live":
            raise DomainError("CALL_CLOSED")
        now = db.now()
        if draft["expires_at"] is not None and now >= instant(draft["expires_at"]):
            raise DomainError("STALE_CONFIRMATION")
        if draft["status"] != "armed":
            raise DomainError("NOT_ARMED")
        user = latest_user(conn, call_id)
        if (
            not user
            or user["seq"] <= draft["armed_seq"]
            or user["received_at"] <= draft["armed_at"]
        ):
            raise DomainError("NOT_ARMED")
        if user["received_at"] >= draft["expires_at"]:
            raise DomainError("STALE_CONFIRMATION")
        if not is_clear_yes(user["text"]):
            raise DomainError("NOT_CONFIRMED")
        slot = checked_draft_slot(conn, call, draft, now)
        for field, value, error in [
            ("provider_id", slot["provider_id"], "SLOT_TAKEN"),
            ("member_id", call["member_id"], "OVERLAP"),
        ]:
            # Column identifiers are constants above, never request values.
            if conn.execute(
                f"SELECT 1 FROM appointments WHERE {field}=? AND status='booked' AND starts_at<? AND ends_at>?",
                (value, slot["ends_at"], slot["starts_at"]),
            ).fetchone():
                invalidate(conn, call, clear_offers=True)
                event(conn, call_id, "preview_invalidated", now)
                raise DomainError(error, persist=True)
        appointment_id = identifier("apt")
        while True:
            confirmation = f"MG-APT-{secrets.randbelow(1_000_000):06}"
            if not conn.execute(
                "SELECT 1 FROM appointments WHERE confirmation=?", (confirmation,)
            ).fetchone():
                break
        conn.execute(
            "UPDATE slots SET state='booked',occupancy_reason='appointment' WHERE id=? AND state='open'",
            (slot["id"],),
        )
        conn.execute("UPDATE drafts SET status='booked' WHERE id=?", (draft["id"],))
        conn.execute(
            "INSERT INTO appointments(id,call_id,member_id,provider_id,slot_id,draft_id,confirmation,starts_at,ends_at,consent_turn_seq,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                appointment_id,
                call_id,
                call["member_id"],
                slot["provider_id"],
                slot["id"],
                draft["id"],
                confirmation,
                slot["starts_at"],
                slot["ends_at"],
                user["seq"],
                utc(now),
            ),
        )
        event(conn, call_id, "appointment_booked", now)
        saved = conn.execute(
            "SELECT * FROM appointments WHERE id=?", (appointment_id,)
        ).fetchone()
        result = confirmation_response(conn, saved)
        # No success leaves this function until the context manager commits.
        if db.now() >= instant(draft["expires_at"]):
            raise DomainError("STALE_CONFIRMATION")
        return result, 201


def get_appointments(db, call_id):
    with db.snapshot() as conn:
        call = get_call(conn, call_id, verified=True, live=False)
        rows = conn.execute(
            "SELECT * FROM appointments WHERE call_id=? AND member_id=? AND starts_at>=? ORDER BY starts_at,id",
            (call_id, call["member_id"], utc(db.now())),
        ).fetchall()
        appointments = [appointment_view(conn, row) for row in rows]
        return {
            "appointments": appointments,
            "speak": confirmation_response(conn, rows[0])["speak"]
            if rows
            else "There is no upcoming appointment saved for this call.",
        }
