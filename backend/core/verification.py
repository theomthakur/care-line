import json
import re
from datetime import timedelta

from .common import event, get_call, get_member, identifier, member_view, utc
from .errors import DomainError

LIVE_WINDOW = timedelta(minutes=5)
DIGITS = {
    word: str(i)
    for i, word in enumerate(
        ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    )
}
DIGITS["oh"] = "0"


def normalize_digits(value):
    pieces = re.split(r"[\s-]+", value.strip().lower())
    normalized = "".join(DIGITS.get(piece, piece) for piece in pieces)
    if not re.fullmatch(r"[0-9]{4}", normalized):
        raise DomainError(
            "INVALID_REQUEST", "Please say the four member digits one at a time."
        )
    return normalized


def verification_task(conn, call_id, now):
    existing = conn.execute(
        "SELECT id FROM tasks WHERE call_id=? AND dedupe_key='verification_failed'",
        (call_id,),
    ).fetchone()
    if existing:
        return existing["id"]
    task_id = identifier("task")
    reference = "MG-" + identifier("VERIFY").upper()
    packet = {
        "reference": reference,
        "category": "verification_failed",
        "summary": "Demo member verification failed after three attempts.",
        "detail": "The caller could not be verified. No member information was disclosed.",
        "caller_verified": False,
        "plan": None,
        "already_tried": ["Three demo verification attempts"],
        "suggested_next_action": "A member services representative should help verify the caller.",
    }
    conn.execute(
        "INSERT INTO tasks(id,call_id,reference,category,detail,dedupe_key,packet_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            task_id,
            call_id,
            reference,
            "verification_failed",
            packet["detail"],
            "verification_failed",
            json.dumps(packet),
            utc(now),
        ),
    )
    event(conn, call_id, "followup_created", now)
    return task_id


def verify_member(db, call_id, member_digits, birth_month):
    with db.transaction() as conn:
        call = get_call(conn, call_id)
        now = db.now()
        if call["verification_status"] == "verified":
            return {
                "status": "verified",
                "member": member_view(get_member(conn, call), now),
                "speak": "Thank you, you're verified.",
            }
        if call["verification_status"] == "locked":
            task_id = verification_task(conn, call_id, now)
            raise DomainError(
                "LOCKED", persist=True, attempts_remaining=0, task_id=task_id
            )
        digits = normalize_digits(member_digits)
        member = conn.execute(
            "SELECT id FROM members WHERE member_digits=? AND birth_month=?",
            (digits, birth_month),
        ).fetchone()
        if member is None:
            attempts = call["verification_attempts"] + 1
            conn.execute(
                "UPDATE calls SET verification_attempts=?, verification_status=? WHERE id=?",
                (attempts, "locked" if attempts == 3 else "unverified", call_id),
            )
            event(conn, call_id, "verification_failed", now)
            if attempts == 3:
                task_id = verification_task(conn, call_id, now)
                raise DomainError(
                    "LOCKED", persist=True, attempts_remaining=0, task_id=task_id
                )
            raise DomainError(
                "VERIFICATION_FAILED", persist=True, attempts_remaining=3 - attempts
            )
        # One live call per member. A call with no activity for LIVE_WINDOW is stale
        # (hung up without finalizing) and does not block a new one.
        cutoff = utc(now - LIVE_WINDOW)
        other = conn.execute(
            """SELECT 1 FROM calls c WHERE c.member_id=? AND c.id<>? AND c.status='live'
               AND COALESCE((SELECT MAX(received_at) FROM turns t WHERE t.call_id=c.id),
                            c.created_at) > ?""",
            (member["id"], call_id, cutoff),
        ).fetchone()
        if other and db.one_call_per_member:
            event(conn, call_id, "member_in_use", now)
            raise DomainError("MEMBER_IN_USE", persist=True)
        conn.execute(
            "UPDATE calls SET member_id=?,verification_status='verified' WHERE id=?",
            (member["id"], call_id),
        )
        event(conn, call_id, "verified", now)
        call = get_call(conn, call_id)
        return {
            "status": "verified",
            "member": member_view(get_member(conn, call), now),
            "speak": "Thank you, you're verified.",
        }
