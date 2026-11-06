"""Tasks, packets, summaries, escalation, admin and routes."""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.ops import summary as summary_mod
from backend.ops.admin import reset_demo, take_slot
from backend.ops.errors import OpsError
from backend.ops.escalation import record_signal
from backend.ops.state import build_state
from backend.ops.summary import build_summary, finalize_call
from backend.ops.tasks import complete_task, create_task, list_tasks

KEY = {"X-Agent-Key": "dev-agent-key"}


# ---------------------------------------------------------------- tasks and packets


def test_packet_is_built_from_stored_rows(conn, stage):
    stage("offered")
    task, created = create_task(
        conn, "c_01", "waitlist", "No open times for Dr. Haddad.", "k1"
    )
    p = task["packet"]
    assert created and p["category"] == "waitlist" and p["reference"].startswith("MG-")
    assert p["caller_verified"] is True and p["plan"] == "Gold 2026"
    assert p["already_tried"] == [
        "Verified identity",
        "Searched primary care near 10023",
        "Explained eligible and excluded providers",
        "Offered open times",
    ]
    assert p["suggested_next_action"] and p["detail"] == "No open times for Dr. Haddad."
    assert "Maya" in p["summary"]


def test_task_creation_is_idempotent_per_incident(conn, stage):
    stage("verified")
    a, first = create_task(conn, "c_01", "caller_requested", "wants a person", "same")
    b, second = create_task(conn, "c_01", "caller_requested", "wants a person", "same")
    assert first and not second and a["task_id"] == b["task_id"]
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    c, third = create_task(conn, "c_01", "caller_requested", "wants a person", "other")
    assert third and c["packet"]["reference"] != a["packet"]["reference"]


def test_unverified_packet_reveals_no_plan(conn, stage):
    stage("unverified")
    p = create_task(conn, "c_01", "caller_requested", "wants a person", "k")[0][
        "packet"
    ]
    assert p["caller_verified"] is False and p["plan"] is None


def test_complete_is_idempotent_and_filterable(conn, stage):
    stage("verified")
    t = create_task(conn, "c_01", "tool_failure", "x", "k")[0]
    assert [x["task_id"] for x in list_tasks(conn, "open")] == [t["task_id"]]
    done = complete_task(conn, t["task_id"])
    again = complete_task(conn, t["task_id"])
    assert (
        done["status"] == "completed" and done["completed_at"] == again["completed_at"]
    )
    assert list_tasks(conn, "open") == [] and len(list_tasks(conn, "completed")) == 1
    with pytest.raises(OpsError) as e:
        complete_task(conn, "nope")
    assert e.value.detail["error"] == "TASK_NOT_FOUND"


# ---------------------------------------------------------------- summary


def test_summary_booked_only_with_a_booked_row(conn, stage):
    stage("armed")  # read-back finished, yes not given
    s = build_summary(conn, "c_01")
    assert (
        s["outcome"] == "not_completed"
        and s["confirmation"] is None
        and "MG-APT" not in s["text"]
    )
    stage("booked")
    s = build_summary(conn, "c_01")
    assert s["outcome"] == "booked" and s["confirmation"] == "MG-APT-4821"


def test_summary_reason_is_first_request_not_the_goodbye(conn, stage):
    stage("booked")
    conn.execute("UPDATE calls SET first_request = NULL")
    conn.execute(
        "INSERT INTO turns VALUES ('c_01', 6, 'x6', 'user', 'Thanks, bye', '2026-11-06T21:01:00Z')"
    )
    assert build_summary(conn, "c_01")["reason"].startswith(
        "Find a new-patient primary care doctor"
    )


def test_summary_unknown_when_commit_cannot_be_reconciled(conn, stage, monkeypatch):
    stage("armed")
    monkeypatch.setattr(summary_mod, "pending_commit", lambda cid: True)
    monkeypatch.setattr(summary_mod, "PENDING_WAIT_S", 0.0)
    s = finalize_call(conn, "c_01")
    assert s["outcome"] == "unknown" and s["confirmation"] is None


def test_finalize_waits_for_a_pending_commit_then_reads_committed_rows(
    conn, stage, monkeypatch
):
    stage("armed")
    polls = {"n": 0}

    def pending(cid):
        polls["n"] += 1
        if polls["n"] == 3:  # the commit lands while finalize waits
            conn.execute(
                "UPDATE slots SET state='booked', occupancy_reason='appointment' WHERE id LIKE 'S-P2-%1500'"
            )
            conn.execute("UPDATE drafts SET status='booked'")
            conn.execute(
                "INSERT INTO appointments (id, call_id, member_id, provider_id, slot_id, draft_id, confirmation, starts_at, ends_at, consent_turn_seq, created_at) "
                "SELECT 'apt_x','c_01','m_maya','P2', d.slot_id, d.id, 'MG-APT-9999', s.starts_at, s.ends_at, 3, '2026-11-06T21:00:46Z' "
                "FROM drafts d JOIN slots s ON s.id = d.slot_id"
            )
        return polls["n"] < 3

    monkeypatch.setattr(summary_mod, "pending_commit", pending)
    assert finalize_call(conn, "c_01")["confirmation"] == "MG-APT-9999"


def test_finalize_twice_is_safe_and_refreshes(conn, stage):
    stage("verified")
    a = finalize_call(conn, "c_01")
    b = finalize_call(conn, "c_01")
    assert a == b and a["outcome"] == "not_completed"
    assert (
        conn.execute("SELECT COUNT(*) FROM events WHERE name='finalized'").fetchone()[0]
        == 1
    )
    assert build_state(conn)["status"] == "finalized"


def test_summary_of_a_call_with_nothing_done_is_honest(conn, stage):
    stage("unverified")
    s = finalize_call(conn, "c_01")
    assert s["outcome"] == "not_completed" and "Nothing was written" in s["text"]


# ---------------------------------------------------------------- escalation


def test_two_tool_failures_in_a_row_make_one_task_and_success_resets(conn, stage):
    stage("verified")
    assert record_signal(conn, "c_01", "tool_failure") is None
    assert record_signal(conn, "c_01", "tool_ok") is None  # streak broken
    assert record_signal(conn, "c_01", "tool_failure") is None
    task = record_signal(conn, "c_01", "tool_failure")
    assert task and task["packet"]["category"] == "tool_failure"
    assert (
        record_signal(conn, "c_01", "tool_failure") is None
    )  # third in the same streak: no duplicate
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_two_unanswered_questions_escalate_once(conn, stage):
    stage("verified")
    assert record_signal(conn, "c_01", "unanswered") is None
    task = record_signal(conn, "c_01", "unanswered")
    assert task and task["packet"]["category"] == "knowledge_gap"
    record_signal(conn, "c_01", "answered")
    record_signal(conn, "c_01", "unanswered")
    second = record_signal(conn, "c_01", "unanswered")  # a new incident is a new task
    assert second and second["task_id"] != task["task_id"]


# ---------------------------------------------------------------- admin


def test_take_slot_blocks_atomically_and_second_attempt_is_taken(conn, stage):
    stage("offered")
    sid = "S-P2-1113-1500"
    assert take_slot(conn, sid) == {
        "ok": True,
        "slot_id": sid,
        "state": "blocked",
        "speak": "",
    }
    row = conn.execute(
        "SELECT state, occupancy_reason FROM slots WHERE id = ?", (sid,)
    ).fetchone()
    assert (row["state"], row["occupancy_reason"]) == (
        "blocked",
        "simulated_other_caller",
    )
    with pytest.raises(OpsError) as e:
        take_slot(conn, sid)
    assert e.value.detail["error"] == "SLOT_TAKEN"
    with pytest.raises(OpsError) as e:
        take_slot(conn, "S-NOPE")
    assert e.value.detail["error"] == "SLOT_NOT_FOUND"
    # the draft is untouched here: only core's confirm may void a preview
    stage("armed")
    take_slot(conn, sid)
    s = build_state(conn)
    assert s["draft"]["status"] == "armed"
    assert next(d for d in s["day_slots"] if d["slot_id"] == sid)["state"] == "blocked"


def test_reset_is_refused_while_a_call_is_live_and_changes_nothing(conn, stage):
    stage("armed")
    with pytest.raises(OpsError) as e:
        reset_demo(conn)
    assert e.value.detail["error"] == "CALL_ACTIVE"
    assert conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 1


def test_reset_is_refused_while_a_commit_is_pending(conn, stage, monkeypatch):
    stage("followup")  # finalized, so only the pending-commit check can refuse
    monkeypatch.setattr(summary_mod, "pending_commit", lambda cid: True)
    with pytest.raises(OpsError) as e:
        reset_demo(conn)
    assert e.value.detail["error"] == "CALL_ACTIVE"


def test_reset_clears_calls_and_restores_slots_but_keeps_fixtures(conn, stage):
    stage("finalized")
    take_slot(conn, "S-P2-1113-1430")
    assert reset_demo(conn) == {"ok": True, "speak": ""}
    for table in ("calls", "turns", "drafts", "appointments", "events", "tasks"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert conn.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM providers").fetchone()[0] == 4
    states = {
        r["id"]: (r["state"], r["occupancy_reason"])
        for r in conn.execute("SELECT id, state, occupancy_reason FROM slots")
    }
    assert states["S-P2-1113-1500"] == ("open", None) and states["S-P2-1113-1430"] == (
        "open",
        None,
    )
    assert any(v == ("booked", "seeded_occupancy") for v in states.values())
    assert build_state(conn) is None


# ---------------------------------------------------------------- routes


def run(coro):
    return asyncio.run(coro)


def test_routes_envelope_and_flow(call, db_path, conn, stage):
    stage("offered")

    async def flow():
        st, b = await call("GET", "/calls/latest")
        assert st == 200 and b["speak"] == "" and b["state"]["call_id"] == "c_01"

        st, b = await call(
            "POST",
            "/calls/c_01/followup",
            {"category": "waitlist", "detail": "No times"},
            KEY,
        )
        assert (
            st == 201
            and b["task"]["packet"]["category"] == "waitlist"
            and b["speak"].startswith("I saved follow-up request M G")
        )
        st2, b2 = await call(
            "POST",
            "/calls/c_01/followup",
            {"category": "waitlist", "detail": "No times"},
            KEY,
        )
        assert st2 == 200 and b2["task"]["task_id"] == b["task"]["task_id"]

        st, b = await call("GET", "/tasks?status=open")
        assert st == 200 and len(b["tasks"]) == 1
        tid = b["tasks"][0]["task_id"]
        st, b = await call("POST", f"/tasks/{tid}/complete", {})
        assert st == 200 and b["task"]["status"] == "completed"
        st, b = await call("POST", "/tasks/zzz/complete", {})
        assert (st, b["error"]) == (404, "TASK_NOT_FOUND")

        st, b = await call("POST", "/admin/reset", {})
        assert (st, b["error"]) == (409, "CALL_ACTIVE")

        st, b = await call("POST", "/calls/c_01/finalize", {}, KEY)
        assert st == 200 and b["summary"]["outcome"] == "followup"
        st, b = await call(
            "POST",
            "/calls/c_01/followup",
            {"category": "waitlist", "detail": "again"},
            KEY,
        )
        assert (st, b["error"]) == (409, "CALL_CLOSED")

        st, b = await call("POST", "/admin/reset", {})
        assert (st, b) == (200, {"ok": True, "speak": ""})
        st, b = await call("GET", "/calls/latest")
        assert (st, b) == (200, {"state": None, "speak": ""})

    run(flow())


def test_agent_routes_require_the_key_and_reject_unknown_fields(call, stage):
    stage("verified")

    async def flow():
        st, b = await call(
            "POST", "/calls/c_01/followup", {"category": "waitlist", "detail": "x"}
        )
        assert (st, b["error"]) == (401, "UNAUTHORIZED")
        st, b = await call(
            "POST",
            "/calls/c_01/followup",
            {"category": "waitlist", "detail": "x"},
            {"X-Agent-Key": "wrong"},
        )
        assert st == 401
        for bad in (
            {"category": "waitlist", "detail": "x", "member_id": "m_maya"},
            {"category": "nope", "detail": "x"},
            {"category": "waitlist", "detail": "  "},
        ):
            st, b = await call("POST", "/calls/c_01/followup", bad, KEY)
            assert (st, b["error"]) == (422, "INVALID_REQUEST"), bad
        st, b = await call("POST", "/calls/missing/finalize", {}, KEY)
        assert (st, b["error"]) == (404, "CALL_NOT_FOUND")
        st, b = await call("POST", "/admin/take-slot", {"slot_id": "S-NOPE"})
        assert (st, b["error"]) == (404, "SLOT_NOT_FOUND")
        st, b = await call("POST", "/admin/take-slot", {})
        assert (st, b["error"]) == (422, "INVALID_REQUEST")
        st, b = await call("GET", "/tasks?status=bogus")
        assert (st, b["error"]) == (422, "INVALID_REQUEST")
        assert set(b) == {"error", "speak"}  # no framework validation arrays or traces

    run(flow())


def test_state_is_json_serialisable_for_every_stage(conn, stage):
    for name in (
        "unverified",
        "verified",
        "offered",
        "preview",
        "armed",
        "conflict",
        "booked",
        "finalized",
        "followup",
        "locked",
    ):
        stage(name)
        json.dumps(build_state(conn))
