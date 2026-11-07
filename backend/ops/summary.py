"""Call summaries, built from stored rows so they cannot claim what did not happen."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Callable
from datetime import timedelta

from . import clock
from .db import immediate
from .errors import OpsError
from .state import _SENSITIVE, REDACTED
from .state import _appointment as _appt_row

# Core registers a function that says whether a confirm for this call is still being
# committed. Default: nothing is pending. Finalize waits, then reads committed rows.
PendingCommit = Callable[[str], bool]
pending_commit: PendingCommit = lambda call_id: False  # noqa: E731
PENDING_WAIT_S = 3.0
# A live call with no activity for this long hung up without the voice agent finalizing it
# (worker killed, line dropped, shutdown hook never ran). Same 5 minutes core uses for
# "stale" in verification.py. Nothing about such a call is guessed: its summary is built
# from the rows that were saved.
ABANDON_AFTER = timedelta(seconds=int(os.getenv("CARELINE_ABANDON_AFTER_S", "300")))


def _reason(conn: sqlite3.Connection, call: sqlite3.Row) -> str:
    if call["first_request"]:
        return call["first_request"]
    for t in conn.execute(
        "SELECT text FROM turns WHERE call_id = ? AND role = 'user' ORDER BY seq",
        (call["id"],),
    ):
        if not _SENSITIVE.search(t["text"]) and t["text"] != REDACTED:
            return t["text"]  # the FIRST stated need, never the last goodbye
    return "No request was stated."


def build_summary(
    conn: sqlite3.Connection, call_id: str, commit_unresolved: bool = False
) -> dict:
    call = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
    if call is None:
        raise OpsError("CALL_NOT_FOUND")
    reason = _reason(conn, call)
    member = None
    if call["member_id"]:
        member = conn.execute(
            "SELECT display_name FROM members WHERE id = ?", (call["member_id"],)
        ).fetchone()
    who = member["display_name"] if member else "The caller"

    appt = _appt_row(conn, call_id)
    if appt:
        return {
            "outcome": "booked",
            "reason": reason,
            "text": (
                f"{who} verified against synthetic records and booked a simulated new-patient visit with "
                f"{appt['doctor']} on {appt['when']}. Confirmation {appt['confirmation']}."
            ),
            "confirmation": appt["confirmation"],
        }
    if commit_unresolved:
        return {
            "outcome": "unknown",
            "reason": reason,
            "text": "The call ended while a booking was being confirmed, and the result could not be verified. Check the schedule before telling the caller anything.",
            "confirmation": None,
        }
    tasks = conn.execute(
        "SELECT reference, packet_json FROM tasks WHERE call_id = ? ORDER BY created_at, id",
        (call_id,),
    ).fetchall()
    if tasks:
        refs = ", ".join(t["reference"] for t in tasks)
        lead = json.loads(tasks[0]["packet_json"])["summary"]
        noun = "Follow-up" if len(tasks) == 1 else "Follow-ups"
        verb = "was" if len(tasks) == 1 else "were"
        return {
            "outcome": "followup",
            "reason": reason,
            "text": f"{lead} {noun} {refs} {verb} saved; no appointment was booked.",
            "confirmation": None,
        }
    return {
        "outcome": "not_completed",
        "reason": reason,
        "text": "The call ended without a booking or a follow-up request. Nothing was written to the schedule.",
        "confirmation": None,
    }


def finalize_call(
    conn: sqlite3.Connection, call_id: str, ended_reason: str | None = None
) -> dict:
    """Mark the call finalized and store its summary. Safe to repeat (refreshes from rows).

    ``ended_reason`` is ``"dropped"`` when the backend closed a call the voice agent never
    finalized; a normal hang-up leaves it out."""
    if not conn.execute("SELECT 1 FROM calls WHERE id = ?", (call_id,)).fetchone():
        raise OpsError("CALL_NOT_FOUND")
    deadline = time.monotonic() + PENDING_WAIT_S
    while pending_commit(call_id) and time.monotonic() < deadline:
        time.sleep(0.05)
    unresolved = pending_commit(call_id)
    with immediate(conn):
        summary = build_summary(conn, call_id, commit_unresolved=unresolved)
        if ended_reason:
            summary["ended_reason"] = ended_reason
        now = clock.utc_str(clock.now())
        row = conn.execute(
            "SELECT status FROM calls WHERE id = ?", (call_id,)
        ).fetchone()
        if row["status"] != "finalized":
            conn.execute(
                "UPDATE calls SET status = 'finalized', finalized_at = ?, summary_json = ? WHERE id = ?",
                (now, json.dumps(summary), call_id),
            )
            conn.execute(
                "INSERT INTO events (call_id, name, created_at) VALUES (?, 'finalized', ?)",
                (call_id, now),
            )
        else:
            conn.execute(
                "UPDATE calls SET summary_json = ? WHERE id = ?",
                (json.dumps(summary), call_id),
            )
    return summary


def close_abandoned(
    conn: sqlite3.Connection, after: timedelta | None = None
) -> list[str]:
    """Finalize live calls that went quiet without being finalized, so they get a summary.

    Idempotent and cheap (one indexed-ish SELECT). A call whose confirmation is still being
    committed is left alone until the next pass."""
    cutoff = clock.utc_str(
        clock.now() - (after if after is not None else ABANDON_AFTER)
    )
    rows = conn.execute(
        """SELECT c.id FROM calls c WHERE c.status = 'live' AND
           MAX(c.created_at,
               COALESCE((SELECT MAX(received_at) FROM turns t WHERE t.call_id = c.id), ''),
               COALESCE((SELECT MAX(created_at) FROM events e WHERE e.call_id = c.id), '')) < ?""",
        (cutoff,),
    ).fetchall()
    closed = []
    for row in rows:
        if pending_commit(row["id"]):
            continue
        finalize_call(conn, row["id"], ended_reason="dropped")
        closed.append(row["id"])
    return closed


# ------------------------------------------------------------------ summary details

_PROBLEM_EVENTS = {
    "slot_taken": "A time the caller chose was taken by someone else.",
    "preview_invalidated": "A read-back was voided and had to be redone.",
    "member_in_use": "The member already had another call in progress.",
}


def _problems(names: list[str], call: sqlite3.Row) -> list[str]:
    out: list[str] = []
    fails = names.count("verification_failed")
    if fails:
        out.append(
            f"Verification did not match {fails} time{'s' if fails != 1 else ''}."
        )
    if call["verification_status"] == "locked":
        out.append("Verification was locked after three failed attempts.")
    for name, text in _PROBLEM_EVENTS.items():
        n = names.count(name)
        if n:
            out.append(text if n == 1 else f"{text[:-1]} ({n} times).")
    return out


def summary_details(conn: sqlite3.Connection, call_id: str) -> dict:
    """Structured facts for the post-call summary, read from stored rows every time.

    Never stored and never model-written: follow-up status changes after the call ends, so
    this is recomputed whenever a finalized call is opened."""
    call = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
    if call is None:
        raise OpsError("CALL_NOT_FOUND")
    names = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM events WHERE call_id = ? ORDER BY id", (call_id,)
        )
    ]
    if call["verification_status"] == "verified":
        verification = "verified"
    elif call["verification_status"] == "locked":
        verification = "locked"
    elif call["verification_attempts"]:
        verification = "failed"
    else:
        verification = "not_attempted"
    appt = _appt_row(conn, call_id)
    provider = None
    if appt:
        provider = {"name": appt["doctor"], "phone": appt["phone"]}
    elif call["selected_provider_id"]:
        p = conn.execute(
            "SELECT name, phone FROM providers WHERE id = ?",
            (call["selected_provider_id"],),
        ).fetchone()
        if p:
            provider = {"name": p["name"], "phone": p["phone"]}
    follow_ups = []
    for t in conn.execute(
        "SELECT reference, status, packet_json FROM tasks WHERE call_id = ? ORDER BY created_at, id",
        (call_id,),
    ):
        packet = json.loads(t["packet_json"])
        follow_ups.append(
            {
                "reference": t["reference"],
                "status": t["status"],
                "category": packet.get("category"),
                "next_action": packet.get("suggested_next_action", ""),
            }
        )
    open_ups = [f for f in follow_ups if f["status"] == "open"]
    base = stored_summary(call["summary_json"])
    if appt:
        next_action = (
            f"Follow up on {open_ups[0]['reference']}: {open_ups[0]['next_action']}"
            if open_ups
            else "No action needed. The appointment is booked."
        )
    elif base.get("outcome") == "unknown":
        next_action = "Check the schedule before telling the caller anything."
    elif open_ups:
        next_action = f"{open_ups[0]['reference']}: {open_ups[0]['next_action']}"
    elif follow_ups:
        next_action = "No action needed. The follow-up request is complete."
    else:
        next_action = "Call the member back if they still need a visit."
    return {
        "verification": verification,
        "provider": provider,
        "appointment": {
            "confirmation": appt["confirmation"],
            "when": appt["when"],
            "doctor": appt["doctor"],
            "phone": appt["phone"],
        }
        if appt
        else None,
        "problems": _problems(names, call),
        "follow_ups": follow_ups,
        "next_action": next_action,
    }


def stored_summary(text: str | None) -> dict:
    try:
        value = json.loads(text) if text else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
