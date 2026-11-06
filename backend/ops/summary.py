"""Call summaries, built from stored rows so they cannot claim what did not happen."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable

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


def finalize_call(conn: sqlite3.Connection, call_id: str) -> dict:
    """Mark the call finalized and store its summary. Safe to repeat (refreshes from rows)."""
    if not conn.execute("SELECT 1 FROM calls WHERE id = ?", (call_id,)).fetchone():
        raise OpsError("CALL_NOT_FOUND")
    deadline = time.monotonic() + PENDING_WAIT_S
    while pending_commit(call_id) and time.monotonic() < deadline:
        time.sleep(0.05)
    unresolved = pending_commit(call_id)
    with immediate(conn):
        summary = build_summary(conn, call_id, commit_unresolved=unresolved)
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
