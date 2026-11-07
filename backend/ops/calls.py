"""Multi-call read model for the operator console.

``list_calls`` summarises every live call and the most recent finished ones in one
read snapshot. Everything is keyed by ``call_id`` and derived from stored rows: a call
is only ``booked`` if an appointment row exists, and nothing here exposes a token,
hash, verification digits, transcript text or another call's data. List rows carry no
transcript at all: the full conversation is only in the selected call's state.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import clock

DEFAULT_RECENT = 20
MAX_RECENT = 100
LIVE_CAP = 100

STAGES = (
    "unverified",
    "locked",
    "verified",
    "searching",
    "offering",
    "readback",
    "awaiting_yes",
    "conflict",
    "booked",
    "followup",
    "ended",
)

_SELECT = """
SELECT c.id, c.status, c.verification_status, c.created_at, c.finalized_at,
       c.selected_provider_id, c.summary_json, c.providers_json,
       m.display_name, m.member_digits,
       d.status AS draft_status, d.expires_at AS draft_expires,
       (SELECT COUNT(*) FROM turns t WHERE t.call_id = c.id) AS turn_count,
       (SELECT MAX(received_at) FROM turns t WHERE t.call_id = c.id) AS last_turn_at,
       (SELECT MAX(created_at) FROM events e WHERE e.call_id = c.id) AS last_event_at,
       (SELECT COUNT(*) FROM tasks k WHERE k.call_id = c.id) AS task_count,
       (SELECT COUNT(*) FROM tasks k WHERE k.call_id = c.id AND k.status = 'open') AS open_tasks,
       (SELECT a.confirmation FROM appointments a
         WHERE a.call_id = c.id AND a.status = 'booked') AS confirmation
FROM calls c
LEFT JOIN members m ON m.id = c.member_id
LEFT JOIN drafts d ON d.id = c.current_draft_id
"""


def _rows(
    conn: sqlite3.Connection, where: str, order: str, limit: int
) -> list[sqlite3.Row]:
    return conn.execute(
        f"{_SELECT} WHERE {where} ORDER BY {order} LIMIT ?", (limit,)
    ).fetchall()


def _events(conn: sqlite3.Connection, ids: list[str]) -> dict[str, list[sqlite3.Row]]:
    out: dict[str, list[sqlite3.Row]] = {i: [] for i in ids}
    if not ids:
        return out
    marks = ",".join("?" * len(ids))
    for r in conn.execute(
        f"SELECT call_id, name, created_at FROM events WHERE call_id IN ({marks}) ORDER BY id",
        ids,
    ):
        out[r["call_id"]].append(r)
    return out


def _last_index(names: list[str], name: str) -> int:
    return len(names) - 1 - names[::-1].index(name) if name in names else -1


def derive_stage(
    row: sqlite3.Row, names: list[str], outcome: str | None, now_s: str
) -> str:
    """Workflow position from stored rows. ``booked`` only with a committed appointment."""
    if row["confirmation"]:
        return "booked"
    if row["status"] == "finalized":
        return "followup" if outcome == "followup" else "ended"
    if row["verification_status"] == "locked":
        return "locked"
    if row["verification_status"] != "verified":
        return "unverified"
    draft = row["draft_status"]
    if draft == "armed" and not (
        row["draft_expires"] and row["draft_expires"] <= now_s
    ):
        return "awaiting_yes"
    if draft in ("slot", "preview"):
        return "readback"
    if _last_index(names, "slot_taken") > max(
        _last_index(names, "slot_selected"), _last_index(names, "availability_offered")
    ):
        return "conflict"
    if row["selected_provider_id"] or "availability_offered" in names:
        return "offering"
    if row["providers_json"] and row["providers_json"] != "[]":
        return "searching"
    return "verified"


def _outcome(row: sqlite3.Row) -> str | None:
    if not row["summary_json"]:
        return None
    try:
        value = json.loads(row["summary_json"])
    except ValueError:
        return None
    return value.get("outcome") if isinstance(value, dict) else None


def _view(row: sqlite3.Row, events: list[sqlite3.Row], now_s: str) -> dict[str, Any]:
    names = [e["name"] for e in events]
    outcome = _outcome(row)
    verified = row["verification_status"] == "verified" and row["display_name"]
    activity = max(
        v
        for v in (
            row["created_at"],
            row["last_turn_at"],
            row["last_event_at"],
            row["finalized_at"],
        )
        if v
    )
    return {
        "call_id": row["id"],
        "status": row["status"],
        "verification": row["verification_status"],
        "member": {
            "name": row["display_name"],
            "id_masked": "***" + row["member_digits"],
        }
        if verified
        else None,
        "stage": derive_stage(row, names, outcome, now_s),
        "created_at": row["created_at"],
        "finalized_at": row["finalized_at"],
        "last_activity_at": activity,
        "turn_count": row["turn_count"],
        "task_count": row["task_count"],
        "open_tasks": row["open_tasks"],
        "outcome": outcome,
        "confirmation": row["confirmation"],
    }


def list_calls(conn: sqlite3.Connection, recent: int = DEFAULT_RECENT) -> list[dict]:
    """Every live call (newest first), then the ``recent`` most recently finished calls."""
    recent = max(0, min(int(recent), MAX_RECENT))
    own_txn = not conn.in_transaction
    if own_txn:
        conn.execute("BEGIN")  # one consistent snapshot across all three queries
    try:
        now_s = clock.utc_str(clock.now())
        rows = _rows(
            conn, "c.status = 'live'", "c.created_at DESC, c.id DESC", LIVE_CAP
        )
        if recent:
            rows += _rows(
                conn,
                "c.status = 'finalized'",
                "c.finalized_at DESC, c.id DESC",
                recent,
            )
        ids = [r["id"] for r in rows]
        events = _events(conn, ids)
        return [_view(r, events[r["id"]], now_s) for r in rows]
    finally:
        if own_txn:
            conn.execute("COMMIT")
