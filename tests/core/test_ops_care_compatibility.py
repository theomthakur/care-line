"""Regression coverage for merging the console with schema-v2 care history."""

import sqlite3
from datetime import date

import pytest

from backend.core.calls import create_call
from backend.core.seed import seed
from backend.ops.admin import reset_demo
from backend.ops.errors import OpsError


def test_console_reset_restores_care_history_and_clears_call_references(db):
    manifest = seed(db, demo_date=date(2026, 11, 6), care_journeys=True)
    case = manifest["cases"][0]
    call_id = create_call(db, "finished-reschedule")[0]["call_id"]
    with db.transaction() as conn:
        conn.execute(
            "UPDATE calls SET verification_status='verified',member_id='M1',"
            "operation='reschedule',reschedule_appointment_id=?,status='finalized',"
            "finalized_at=created_at WHERE id=?",
            (case["appointment_id"], call_id),
        )
        conn.execute(
            "UPDATE appointments SET status='rescheduled',version=2 WHERE id=?",
            (case["appointment_id"],),
        )
        conn.execute(
            "UPDATE slots SET state='open',occupancy_reason=NULL WHERE id=?",
            (case["original_slot_id"],),
        )
        conn.execute(
            "UPDATE slots SET state='booked',occupancy_reason='appointment' WHERE id=?",
            (case["replacement_slot_id"],),
        )
        conn.execute(
            "INSERT INTO appointments(id,member_id,provider_id,slot_id,confirmation,starts_at,ends_at,created_at,source,replaces_appointment_id) "
            "SELECT 'replacement',a.member_id,a.provider_id,s.id,'MG-DEMO-REPLACEMENT',s.starts_at,s.ends_at,a.created_at,'synthetic_fixture',a.id "
            "FROM appointments a JOIN slots s ON s.id=? WHERE a.id=?",
            (case["replacement_slot_id"], case["appointment_id"]),
        )
        conn.execute("UPDATE referrals SET status='revoked' WHERE id='REF-M2-CARD'")
    with db.transaction() as conn:
        assert reset_demo(conn) == {"ok": True, "speak": ""}
    with db.snapshot() as conn:
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert not conn.execute("SELECT 1 FROM calls").fetchone()
        assert [
            dict(row) for row in conn.execute("SELECT * FROM appointments ORDER BY id")
        ] == manifest["appointments"]
        assert [
            dict(row) for row in conn.execute("SELECT * FROM referrals ORDER BY id")
        ] == manifest["referrals"]
        assert [
            dict(
                conn.execute("SELECT * FROM slots WHERE id=?", (row["id"],)).fetchone()
            )
            for row in manifest["slots"]
        ] == manifest["slots"]
    # Reset and seed retries both preserve the same baseline.
    with db.transaction() as conn:
        reset_demo(conn)
    assert seed(db, demo_date=date(2026, 11, 6), care_journeys=True) == manifest


def test_console_reset_with_care_history_is_refused_during_live_call(db):
    manifest = seed(db, demo_date=date(2026, 11, 6), care_journeys=True)
    create_call(db, "active-care-call")
    with pytest.raises(OpsError) as error, db.transaction() as conn:
        reset_demo(conn)
    assert error.value.detail["error"] == "CALL_ACTIVE"
    with db.snapshot() as conn:
        assert [
            dict(row) for row in conn.execute("SELECT * FROM appointments ORDER BY id")
        ] == manifest["appointments"]
        assert conn.execute("SELECT count(*) FROM calls").fetchone()[0] == 1


def test_console_reset_failure_rolls_back_history_deletion(db):
    manifest = seed(db, demo_date=date(2026, 11, 6), care_journeys=True)
    with db.transaction() as conn:
        conn.execute(
            "CREATE TRIGGER fail_reset BEFORE DELETE ON referrals BEGIN SELECT RAISE(ABORT, 'reset failure'); END"
        )
    with (
        pytest.raises(sqlite3.IntegrityError, match="reset failure"),
        db.transaction() as conn,
    ):
        reset_demo(conn)
    with db.snapshot() as conn:
        assert [
            dict(row) for row in conn.execute("SELECT * FROM appointments ORDER BY id")
        ] == manifest["appointments"]
        assert [
            dict(row) for row in conn.execute("SELECT * FROM referrals ORDER BY id")
        ] == manifest["referrals"]
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
