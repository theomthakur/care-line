"""Demo/admin operations: simulate another caller, and reset (refused while active)."""

from __future__ import annotations

import sqlite3

from . import summary as summary_mod
from .db import immediate
from .errors import OpsError


def take_slot(conn: sqlite3.Connection, slot_id: str) -> dict:
    """Atomically block an open slot as a simulated other caller. Invents no identity."""
    with immediate(conn):
        row = conn.execute(
            "SELECT state FROM slots WHERE id = ?", (slot_id,)
        ).fetchone()
        if row is None:
            raise OpsError("SLOT_NOT_FOUND")
        if row["state"] != "open":
            raise OpsError("SLOT_TAKEN")
        conn.execute(
            "UPDATE slots SET state = 'blocked', occupancy_reason = 'simulated_other_caller' WHERE id = ? AND state = 'open'",
            (slot_id,),
        )
        # Only the slot changes. Core's confirm later fails with SLOT_TAKEN and voids the preview.
        return {"ok": True, "slot_id": slot_id, "state": "blocked", "speak": ""}


def reset_demo(conn: sqlite3.Connection) -> dict:
    """Clear calls, turns, drafts, appointments, events and tasks; restore slot fixtures.

    Refused with CALL_ACTIVE while any call is live or a commit is pending. Keeps plans,
    members, plan_sections, providers, provider_networks and the slot rows themselves.
    """
    with immediate(conn):
        live = conn.execute("SELECT id FROM calls WHERE status = 'live'").fetchall()
        if live or any(
            summary_mod.pending_commit(r["id"])
            for r in conn.execute("SELECT id FROM calls")
        ):
            raise OpsError("CALL_ACTIVE")
        conn.execute("UPDATE calls SET current_draft_id = NULL")
        for table in ("identity_reviews", "call_access", "legal_holds"):
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                conn.execute(f"DELETE FROM {table}")
        for table in ("tasks", "events", "appointments", "drafts", "turns", "calls"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute(
            "UPDATE slots SET state = seed_state, "
            "occupancy_reason = CASE seed_state WHEN 'booked' THEN 'seeded_occupancy' ELSE NULL END"
        )
    return {"ok": True, "speak": ""}
