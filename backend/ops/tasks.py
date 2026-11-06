"""Follow-up tasks. ``create_task`` is idempotent per (call, dedupe_key)."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid

from . import clock
from .db import immediate
from .errors import OpsError
from .packet import build_packet

CATEGORIES = (
    "caller_requested",
    "knowledge_gap",
    "verification_failed",
    "tool_failure",
    "safety",
    "policy_required",
    "waitlist",
)


def task_view(row: sqlite3.Row) -> dict:
    return {
        "task_id": row["id"],
        "call_id": row["call_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
        "packet": json.loads(row["packet_json"]),
    }


def _next_reference(conn: sqlite3.Connection) -> str:
    top = 4800
    for r in conn.execute("SELECT reference FROM tasks"):
        m = re.fullmatch(r"MG-(\d+)", r["reference"])
        if m:
            top = max(top, int(m.group(1)))
    return f"MG-{top + 1}"


def create_task(
    conn: sqlite3.Connection, call_id: str, category: str, detail: str, dedupe_key: str
) -> tuple[dict, bool]:
    """Create the task and its packet, or return the existing one for this incident.

    Returns ``(task, created)``. Core may call this for a ``verification_failed`` lock.
    """
    if category not in CATEGORIES:
        raise OpsError("INVALID_REQUEST")
    with immediate(conn):
        existing = conn.execute(
            "SELECT * FROM tasks WHERE call_id = ? AND dedupe_key = ?",
            (call_id, dedupe_key),
        ).fetchone()
        if existing:
            return task_view(existing), False
        if not conn.execute("SELECT 1 FROM calls WHERE id = ?", (call_id,)).fetchone():
            raise OpsError("CALL_NOT_FOUND")
        ref = _next_reference(conn)
        packet = build_packet(conn, call_id, category, detail, ref)
        now = clock.utc_str(clock.now())
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO tasks (id, call_id, reference, category, detail, dedupe_key, status, packet_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)",
            (
                task_id,
                call_id,
                ref,
                category,
                detail,
                dedupe_key,
                json.dumps(packet),
                now,
            ),
        )
        conn.execute(
            "INSERT INTO events (call_id, name, created_at, detail_json) VALUES (?, 'followup_created', ?, ?)",
            (call_id, now, json.dumps({"reference": ref, "category": category})),
        )
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return task_view(row), True


def list_tasks(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    if status not in (None, "open", "completed"):
        raise OpsError("INVALID_REQUEST")
    sql = "SELECT * FROM tasks"
    args: tuple = ()
    if status:
        sql += " WHERE status = ?"
        args = (status,)
    sql += " ORDER BY created_at DESC, id DESC"
    return [task_view(r) for r in conn.execute(sql, args)]


def complete_task(conn: sqlite3.Connection, task_id: str) -> dict:
    with immediate(conn):
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise OpsError("TASK_NOT_FOUND")
        if row["status"] != "completed":
            conn.execute(
                "UPDATE tasks SET status = 'completed', completed_at = ? WHERE id = ?",
                (clock.utc_str(clock.now()), task_id),
            )
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return task_view(row)


def dedupe_key_for(category: str, detail: str) -> str:
    """Same call + category + detail retried -> same task (contract: 200 replay)."""
    return f"followup:{category}:{uuid.uuid5(uuid.NAMESPACE_OID, detail.strip())}"
