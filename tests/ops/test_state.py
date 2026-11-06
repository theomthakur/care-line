"""The read model must match contracts/examples/state-*.json and never overstate."""

from __future__ import annotations

import json

import pytest

from backend.ops.state import build_state
from tests.ops.conftest import EXAMPLES

STAGES = [
    "unverified",
    "verified",
    "offered",
    "preview",
    "armed",
    "conflict",
    "booked",
    "finalized",
]


def _example(name):
    return json.loads((EXAMPLES / f"state-{name}.json").read_text())["state"]


def _normalise(state):
    """Drop values that are legitimately generated (ids, wall-clock stamps)."""
    s = json.loads(json.dumps(state))
    if s.get("appointment"):
        s["appointment"]["appointment_id"] = "<id>"
    for t in s.get("tasks", []):
        t["task_id"] = "<id>"
        t["created_at"] = t["completed_at"] = "<ts>"
        t["packet"]["reference"] = "<ref>"
    return s


@pytest.mark.parametrize("name", STAGES)
def test_state_matches_contract_example(conn, stage, name):
    stage(name)
    got, want = _normalise(build_state(conn)), _normalise(_example(name))
    # The example lists only the two slots of interest; the real read model returns the
    # provider's whole day. Every example slot must appear with identical fields.
    by_id = {d["slot_id"]: d for d in got.pop("day_slots")}
    for d in want.pop("day_slots"):
        assert by_id[d["slot_id"]] == d
    assert got == want


def test_followup_state_shape_matches_example(conn, stage):
    stage("followup")
    got, want = _normalise(build_state(conn)), _normalise(_example("followup"))
    assert set(got) == set(want)
    for key in set(want) - {"tasks", "summary", "day_slots"}:
        assert got[key] == want[key], key
    assert got["tasks"][0]["packet"].keys() == want["tasks"][0]["packet"].keys()
    assert (
        got["summary"]["outcome"] == "followup"
        and got["summary"]["confirmation"] is None
    )


def test_no_call_returns_none(conn):
    assert build_state(conn) is None


def test_booking_card_exists_only_with_a_committed_row(conn, stage):
    for name in ("preview", "armed", "conflict", "followup"):
        stage(name)
        assert build_state(conn)["appointment"] is None
    stage("booked")
    assert build_state(conn)["appointment"]["confirmation"] == "MG-APT-4821"


def test_expired_armed_draft_is_not_projected_as_a_hold(conn, stage, monkeypatch):
    from datetime import datetime, timezone

    from backend.ops import clock

    stage("armed")
    assert build_state(conn)["draft"]["status"] == "armed"
    monkeypatch.setattr(
        clock, "now", lambda: datetime(2026, 11, 6, 21, 3, 0, tzinfo=timezone.utc)
    )
    assert build_state(conn)["draft"] is None


def test_verification_answers_are_masked_and_no_secrets_leak(conn, stage):
    stage("verified")
    raw = conn.execute("SELECT text FROM turns WHERE seq = 1").fetchone()["text"]
    assert "4417" in raw or "four" in raw  # stored for consent checks
    state = build_state(conn)
    assert state["turns"][0]["text"] == "[Demo verification details redacted]"
    blob = json.dumps(state).lower()
    for secret in (
        "dev-token-not-for-display",
        "details_hash",
        "member_digits",
        "birth_month",
        "token",
    ):
        assert secret not in blob


def test_locked_caller_sees_no_member_and_masked_attempts(conn, stage):
    stage("locked")
    s = build_state(conn)
    assert s["verified"] is False and s["member"] is None
    assert all(
        t["text"] == "[Demo verification details redacted]"
        for t in s["turns"]
        if t["role"] == "user"
    )
    assert s["tasks"][0]["packet"]["category"] == "verification_failed"
    assert s["tasks"][0]["packet"]["plan"] is None


def test_latest_call_wins_and_nothing_leaks_between_calls(conn, stage):
    stage("booked")
    conn.execute(
        "INSERT INTO calls (id, room, created_at) VALUES ('c_02', 'room-2', '2026-11-06T21:30:00Z')"
    )
    s = build_state(conn)
    assert s["call_id"] == "c_02"
    assert (
        s["appointment"] is None
        and s["turns"] == []
        and s["tasks"] == []
        and s["member"] is None
    )
    assert s["day_slots"] == [] and s["events"] == []


def test_latest_call_tie_breaks_by_id(conn):
    for cid in ("c_01", "c_02"):
        conn.execute(
            "INSERT INTO calls (id, room, created_at) VALUES (?, ?, '2026-11-06T21:00:00Z')",
            (cid, cid),
        )
    assert build_state(conn)["call_id"] == "c_02"
