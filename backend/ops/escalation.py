"""Consecutive-failure counters for auto-escalation (plan section 8).

Thresholds: 2 unanswered questions in a row, 2 tool failures in a row. A success resets
the matching counter. Verification locking (3 failures) is core's. These are library
functions only: how the agent reports the signals is still to be agreed (contracts/api.md,
agreement item 6), so no route calls them yet.
"""

from __future__ import annotations

import sqlite3
from typing import Literal

from .db import immediate
from .tasks import create_task

Signal = Literal["unanswered", "answered", "tool_failure", "tool_ok"]
THRESHOLD = 2


def record_signal(
    conn: sqlite3.Connection, call_id: str, signal: Signal
) -> dict | None:
    """Apply one signal. Returns the new task when this signal crosses a threshold."""
    with immediate(conn):
        row = conn.execute(
            "SELECT unanswered_count, tool_failure_count FROM calls WHERE id = ?",
            (call_id,),
        ).fetchone()
        if row is None:
            return None
        un, tf = row["unanswered_count"], row["tool_failure_count"]
        if signal == "answered":
            un = 0
        elif signal == "tool_ok":
            tf = 0
        elif signal == "unanswered":
            un += 1
        elif signal == "tool_failure":
            tf += 1
        task = None
        # One task per incident: the incident number is the count of completed streaks.
        if signal == "unanswered" and un == THRESHOLD:
            task, _ = create_task(
                conn,
                call_id,
                "knowledge_gap",
                "Two questions in a row had no supported answer.",
                f"auto:unanswered:{_incident(conn, call_id, 'knowledge_gap')}",
            )
        if signal == "tool_failure" and tf == THRESHOLD:
            task, _ = create_task(
                conn,
                call_id,
                "tool_failure",
                "Two tool calls failed in a row.",
                f"auto:tool_failure:{_incident(conn, call_id, 'tool_failure')}",
            )
        conn.execute(
            "UPDATE calls SET unanswered_count = ?, tool_failure_count = ? WHERE id = ?",
            (un, tf, call_id),
        )
        return task


def _incident(conn: sqlite3.Connection, call_id: str, category: str) -> int:
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM tasks WHERE call_id = ? AND category = ?",
        (call_id, category),
    ).fetchone()["n"]
    return n + 1
