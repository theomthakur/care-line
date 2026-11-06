"""Console read model: one database snapshot -> the ``State`` object in contracts/api.md.

Read-only. Nothing here decides a booking: an appointment card exists only if an
``appointments`` row exists, and a draft is projected only while it is live.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from . import clock

VERIFICATION_EVENTS = ("verified", "verification_failed", "verification_locked")
_DIGIT_WORDS = r"(?:zero|oh|one|two|three|four|for|five|six|seven|eight|nine)"
_SENSITIVE = re.compile(
    rf"\b\d{{4}}\b|\b\d(?:[\s\-]+\d){{2,}}\b|\b{_DIGIT_WORDS}(?:[\s\-]+{_DIGIT_WORDS}){{2,}}\b"
    r"|\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b",
    re.I,
)
REDACTED = "[Demo verification details redacted]"


def _j(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


def latest_call_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT id FROM calls ORDER BY created_at DESC, id DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


def _member(conn: sqlite3.Connection, member_id: str | None, today: str) -> dict | None:
    if not member_id:
        return None
    m = conn.execute(
        "SELECT m.display_name, m.member_digits, m.coverage_start, m.coverage_end, p.name AS plan, p.network "
        "FROM members m JOIN plans p ON p.id = m.plan_id WHERE m.id = ?",
        (member_id,),
    ).fetchone()
    if not m:
        return None
    return {
        "name": m["display_name"],
        "id_masked": "***" + m["member_digits"],
        "plan": m["plan"],
        "network": m["network"],
        "active": m["coverage_start"] <= today <= m["coverage_end"],
    }


def mask_turn(
    role: str, text: str, received_at: str, unresolved: bool, boundary: str | None
) -> str:
    """Hide verification answers: any caller turn that looks like digits or a birth
    month while the call is unverified, or at/before the moment verification resolved."""
    in_window = unresolved or (boundary is not None and received_at <= boundary)
    if role == "user" and in_window and _SENSITIVE.search(text):
        return REDACTED
    return text


def _turns(
    conn: sqlite3.Connection, call: sqlite3.Row, events: list[sqlite3.Row]
) -> list[dict]:
    created = clock.parse_utc(call["created_at"])
    boundary = None
    for e in events:
        if e["name"] in VERIFICATION_EVENTS:
            boundary = e["created_at"]
    unresolved = (
        call["verification_status"] != "verified"
    )  # failed/locked/in-progress callers
    out = []
    for t in conn.execute(
        "SELECT seq, role, text, received_at FROM turns WHERE call_id = ? ORDER BY seq",
        (call["id"],),
    ):
        text = mask_turn(t["role"], t["text"], t["received_at"], unresolved, boundary)
        secs = (clock.parse_utc(t["received_at"]) - created).total_seconds()
        out.append(
            {
                "seq": t["seq"],
                "role": t["role"],
                "text": text,
                "received_at": t["received_at"],
                "t": round(max(secs, 0.0), 1),
            }
        )
    return out


def _draft(conn: sqlite3.Connection, call: sqlite3.Row, now_s: str) -> dict | None:
    if not call["current_draft_id"]:
        return None
    d = conn.execute(
        "SELECT * FROM drafts WHERE id = ?", (call["current_draft_id"],)
    ).fetchone()
    if not d or d["status"] == "invalidated":
        return None
    # An armed draft whose window has passed is not a hold; never imply one.
    if d["status"] == "armed" and d["expires_at"] and d["expires_at"] <= now_s:
        return None
    return {
        "slot_id": d["slot_id"],
        "revision": d["revision"],
        "status": d["status"],
        "armed_seq": d["armed_seq"],
        "expires_at": d["expires_at"],
    }


def _appointment(conn: sqlite3.Connection, call_id: str) -> dict | None:
    a = conn.execute(
        "SELECT a.*, p.name AS doctor, p.phone FROM appointments a JOIN providers p ON p.id = a.provider_id "
        "WHERE a.call_id = ? AND a.status = 'booked'",
        (call_id,),
    ).fetchone()
    if not a:
        return None
    return {
        "appointment_id": a["id"],
        "status": "booked",
        "confirmation": a["confirmation"],
        "provider_id": a["provider_id"],
        "slot_id": a["slot_id"],
        "doctor": a["doctor"],
        "phone": a["phone"],
        "starts_at": a["starts_at"],
        "ends_at": a["ends_at"],
        "timezone": "America/New_York",
        "when": clock.spoken(a["starts_at"]),
        "simulated": True,
    }


def _day_slots(
    conn: sqlite3.Connection,
    call: sqlite3.Row,
    draft_slot: str | None,
    offered: list[dict],
    appt: dict | None,
) -> list[dict]:
    provider = call["selected_provider_id"]
    if not provider:
        return []
    anchor: datetime | None = None
    chosen = appt["slot_id"] if appt else draft_slot
    if chosen:
        row = conn.execute(
            "SELECT starts_at FROM slots WHERE id = ?", (chosen,)
        ).fetchone()
        if row:
            anchor = clock.parse_utc(row["starts_at"]).astimezone(clock.ET)
    if anchor is None and offered:
        anchor = clock.parse_utc(offered[0]["starts_at"]).astimezone(clock.ET)
    if anchor is None:
        q = _j(call["availability_query_json"], None)
        if isinstance(q, dict) and q.get("date_from"):
            try:
                anchor = datetime.strptime(q["date_from"], "%Y-%m-%d").replace(
                    tzinfo=clock.ET
                )
            except ValueError:
                anchor = None
    if anchor is None:
        return []
    start = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    lo = clock.utc_str(start.astimezone(timezone.utc))
    hi = clock.utc_str(end.astimezone(timezone.utc))
    offered_ids = {o["slot_id"] for o in offered}
    out = []
    for s in conn.execute(
        "SELECT id, starts_at, ends_at, state FROM slots WHERE provider_id = ? AND starts_at >= ? AND starts_at < ? ORDER BY starts_at",
        (provider, lo, hi),
    ):
        out.append(
            {
                "slot_id": s["id"],
                "starts_at": s["starts_at"],
                "ends_at": s["ends_at"],
                "text": clock.spoken(s["starts_at"]),
                "state": s["state"],
                "offered": s["id"] in offered_ids,
                "selected": s["id"] == chosen,
            }
        )
    return out


def build_state(conn: sqlite3.Connection, call_id: str | None = None) -> dict | None:
    """Return the State for ``call_id`` (default: latest call), or None before any call."""
    own_txn = not conn.in_transaction
    if own_txn:
        conn.execute("BEGIN")  # one consistent snapshot for every query below
    try:
        call_id = call_id or latest_call_id(conn)
        if call_id is None:
            return None
        call = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
        if call is None:
            return None
        now = clock.now()
        now_s = clock.utc_str(now)
        today = now.astimezone(clock.ET).strftime("%Y-%m-%d")
        events = conn.execute(
            "SELECT name, created_at FROM events WHERE call_id = ? ORDER BY id",
            (call_id,),
        ).fetchall()
        offered = _j(call["offered_slots_json"], [])
        draft = _draft(conn, call, now_s)
        appt = _appointment(conn, call_id)
        from .tasks import task_view  # local import: tasks imports packet/state helpers

        tasks = [
            task_view(r)
            for r in conn.execute(
                "SELECT * FROM tasks WHERE call_id = ? ORDER BY created_at, id",
                (call_id,),
            )
        ]
        return {
            "call_id": call["id"],
            "status": call["status"],
            "verified": call["verification_status"] == "verified",
            "member": _member(conn, call["member_id"], today),
            "request": {
                "version": call["request_version"],
                "specialty": call["specialty"],
                "zip": call["zip"],
            },
            "turns": _turns(conn, call, events),
            "providers": _j(call["providers_json"], []),
            "excluded": _j(call["excluded_json"], []),
            "selected": call["selected_provider_id"],
            "evidence": _j(call["evidence_json"], []),
            "offered_slots": offered,
            "draft": draft,
            "appointment": appt,
            "day_slots": _day_slots(
                conn, call, draft["slot_id"] if draft else None, offered, appt
            ),
            "tasks": tasks,
            "summary": _j(call["summary_json"], None),
            "events": [e["name"] for e in events],
        }
    finally:
        if own_txn:
            conn.execute("COMMIT")
