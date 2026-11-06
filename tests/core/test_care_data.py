import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from backend.core.db import Database
from backend.core.models import CareAppointment, Provider, Referral, RescheduleRequest
from backend.core.seed import seed


def test_care_fixtures_have_history_and_available_replacements(db):
    manifest = seed(db, demo_date=date(2026, 11, 6), care_journeys=True)
    assert len(manifest["cases"]) == 13
    with db.snapshot() as conn:
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert not conn.execute("SELECT 1 FROM calls").fetchone()
        assert not conn.execute("SELECT 1 FROM turns").fetchone()
        assert (
            conn.execute(
                "SELECT count(*) FROM appointments WHERE status='completed'"
            ).fetchone()[0]
            == 4
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM appointments WHERE status='booked'"
            ).fetchone()[0]
            == 4
        )
        for row in conn.execute("SELECT * FROM appointments"):
            assert row["source"] == "synthetic_fixture"
            assert (
                row["call_id"] is None
                and row["draft_id"] is None
                and row["consent_turn_seq"] is None
            )
        for case in manifest["cases"][:4]:
            source = conn.execute(
                "SELECT * FROM appointments WHERE id=?", (case["appointment_id"],)
            ).fetchone()
            old = conn.execute(
                "SELECT * FROM slots WHERE id=?", (case["original_slot_id"],)
            ).fetchone()
            target = conn.execute(
                "SELECT * FROM slots WHERE id=?", (case["replacement_slot_id"],)
            ).fetchone()
            taken = conn.execute(
                "SELECT * FROM slots WHERE id=?", (case["unavailable_slot_id"],)
            ).fetchone()
            assert source["slot_id"] == old["id"] and old["state"] == "booked"
            assert old["occupancy_reason"] == "appointment"
            assert target["state"] == "open" and taken["state"] == "booked"
            assert source["provider_id"] == target["provider_id"] == case["provider_id"]
            assert target["starts_at"] > source["starts_at"]
        flags = dict(conn.execute("SELECT id,specialist_referral_required FROM plans"))
        assert flags == {"GOLD": 0, "BASIC": 1}
        valid = conn.execute(
            "SELECT * FROM referrals WHERE id='REF-M2-CARD'"
        ).fetchone()
        expired = conn.execute(
            "SELECT * FROM referrals WHERE id='REF-M5-DERM'"
        ).fetchone()
        assert valid["status"] == "verified" and valid["valid_until"] >= "2026-11-13"
        assert expired["status"] == "verified" and expired["valid_until"] < "2026-11-06"
        expires_case = manifest["cases"][-1]
        later = conn.execute(
            "SELECT starts_at FROM slots WHERE id=?",
            (expires_case["replacement_slot_id"],),
        ).fetchone()[0]
        assert later[:10] > valid["valid_until"]
        assert (
            conn.execute(
                "SELECT status FROM referrals WHERE id='REF-M5-CARD'"
            ).fetchone()[0]
            == "revoked"
        )
        assert not conn.execute(
            "SELECT 1 FROM referrals WHERE member_id='M4'"
        ).fetchone()
        for referral in conn.execute("SELECT * FROM referrals"):
            completed = conn.execute(
                "SELECT * FROM appointments WHERE id=?",
                (referral["referring_appointment_id"],),
            ).fetchone()
            assert completed["status"] == "completed"
            assert completed["provider_id"] == referral["referring_provider_id"]
            Referral.model_validate(dict(referral))


def test_base_seed_does_not_install_history(db):
    with db.snapshot() as conn:
        assert not conn.execute("SELECT 1 FROM appointments").fetchone()
        assert not conn.execute("SELECT 1 FROM demo_fixture_sets").fetchone()
        assert (
            conn.execute(
                "SELECT count(*) FROM providers WHERE specialty <> 'primary care'"
            ).fetchone()[0]
            == 5
        )


def test_reseed_does_not_undo_a_later_reschedule(db):
    manifest = seed(db, demo_date=date(2026, 11, 6), care_journeys=True)
    case = manifest["cases"][0]
    with db.transaction() as conn:
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
    assert seed(db, demo_date=date(2026, 11, 6), care_journeys=True) == manifest
    db.initialize()
    with db.snapshot() as conn:
        assert conn.execute(
            "SELECT status,version FROM appointments WHERE id=?",
            (case["appointment_id"],),
        ).fetchone()[:] == ("rescheduled", 2)
        assert (
            conn.execute(
                "SELECT state FROM slots WHERE id=?", (case["replacement_slot_id"],)
            ).fetchone()[0]
            == "booked"
        )
        assert (
            conn.execute(
                "SELECT state FROM slots WHERE id=?", (case["original_slot_id"],)
            ).fetchone()[0]
            == "open"
        )
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    with pytest.raises(ValueError, match="different demo date"):
        seed(db, demo_date=date(2026, 11, 9), care_journeys=True)


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE referrals SET member_id='M1' WHERE id='REF-M2-CARD'",
        "UPDATE appointments SET referral_id='REF-M2-CARD' WHERE id='FIX-MAYA-SPECIALIST-BOOKED'",
        "UPDATE appointments SET replaces_appointment_id='FIX-RILEY-PCP-BOOKED' WHERE id='FIX-MAYA-PCP-BOOKED'",
        "UPDATE referrals SET source='caller_report' WHERE id='REF-M2-CARD'",
        "UPDATE referrals SET valid_until=NULL WHERE id='REF-M2-CARD'",
        "UPDATE appointments SET source='voice' WHERE id='FIX-MAYA-PCP-BOOKED'",
        "UPDATE appointments SET replaces_appointment_id=id WHERE id='FIX-MAYA-PCP-BOOKED'",
        "UPDATE appointments SET status='unknown' WHERE id='FIX-MAYA-PCP-BOOKED'",
    ],
)
def test_care_constraints_prevent_invalid_provenance_and_member_links(db, change):
    seed(db, demo_date=date(2026, 11, 6), care_journeys=True)
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
        conn.execute(change)


def test_care_install_refuses_live_calls(db):
    from backend.core.calls import create_call

    create_call(db, "active")
    with pytest.raises(ValueError, match="live calls"):
        seed(db, demo_date=date(2026, 11, 6), care_journeys=True)
    with db.snapshot() as conn:
        assert not conn.execute("SELECT 1 FROM appointments").fetchone()


def test_extension_models():
    assert (
        Provider.model_validate(
            {
                "id": "P6",
                "name": "Dr. Nina Rao",
                "specialty": "cardiology",
                "zip": "10023",
                "phone": "212-555-0106",
                "accepting_new_patients": True,
            }
        ).specialty
        == "cardiology"
    )
    assert RescheduleRequest(
        appointment_id="FIX-RILEY-SPECIALIST-BOOKED"
    ).appointment_id.startswith("FIX-")
    appointment = json.loads(
        (
            Path(__file__).parents[2] / "contracts/examples/booking-confirmed.json"
        ).read_text()
    )["appointment"]
    extended = CareAppointment.model_validate(
        {
            **appointment,
            "status": "rescheduled",
            "specialty": "cardiology",
            "source": "synthetic_fixture",
            "version": 2,
        }
    )
    assert extended.status == "rescheduled"


def legacy_database(path):
    conn = sqlite3.connect(path)
    conn.executescript((Path(__file__).parent / "fixtures/schema_v1.sql").read_text())
    conn.executescript("""
        INSERT INTO plans VALUES ('GOLD','Gold 2026','METRO');
        INSERT INTO plans VALUES ('BASIC','Basic 2026','VALUE');
        INSERT INTO members VALUES ('M1','Maya Torres','Maya T.','4417',4,'GOLD','2026-01-01','2026-12-31');
        INSERT INTO providers VALUES ('P2','Dr. Omar Haddad','primary care','10023','212-555-0102',1);
        INSERT INTO provider_networks VALUES ('P2','METRO');
        INSERT INTO slots(id,provider_id,starts_at,ends_at,state,occupancy_reason) VALUES ('old-slot','P2','2026-11-13T19:30:00Z','2026-11-13T20:00:00Z','booked','appointment');
        INSERT INTO calls(id,room,created_at,verification_status,member_id,request_version,specialty,selected_provider_id)
            VALUES ('old-call','old-room','2026-11-06T21:00:00Z','verified','M1',1,'primary care','P2');
        INSERT INTO turns VALUES ('old-call',1,'old-yes','user','yes','2026-11-06T21:00:01Z');
        INSERT INTO drafts(id,call_id,member_id,provider_id,slot_id,revision,request_version,status,token,details_hash,read_back,preview_user_seq,armed_seq,armed_at,expires_at,created_at)
            VALUES ('old-draft','old-call','M1','P2','old-slot',1,1,'booked','old-token',printf('%064d',0),'Original read-back',0,0,'2026-11-06T21:00:00Z','2026-11-06T21:01:30Z','2026-11-06T21:00:00Z');
        UPDATE calls SET current_draft_id='old-draft' WHERE id='old-call';
        INSERT INTO appointments VALUES ('old-apt','old-call','M1','P2','old-slot','old-draft','MG-APT-123456','booked','2026-11-13T19:30:00Z','2026-11-13T20:00:00Z',1,'2026-11-06T21:00:01Z');
    """)
    conn.close()


def test_migration_preserves_existing_booking_consent_and_current_draft(
    tmp_path, clock
):
    path = tmp_path / "legacy.db"
    legacy_database(path)
    conn = sqlite3.connect(path)
    before = {
        table: (
            list(conn.execute(f"PRAGMA table_info({table})")),
            list(conn.execute(f"SELECT * FROM {table}")),
        )
        for table in ("calls", "turns", "drafts", "appointments", "slots")
    }
    conn.close()
    db = Database(path, clock=clock)
    db.initialize()
    db.initialize()
    with db.snapshot() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert dict(
            conn.execute("SELECT id,specialist_referral_required FROM plans")
        ) == {"GOLD": 0, "BASIC": 1}
        for table, (columns, rows) in before.items():
            names = ",".join(column[1] for column in columns)
            assert [
                tuple(row) for row in conn.execute(f"SELECT {names} FROM {table}")
            ] == rows
        saved = conn.execute("SELECT * FROM appointments WHERE id='old-apt'").fetchone()
        assert saved["source"] == "voice" and saved["version"] == 1
    with db.transaction() as conn:
        conn.execute("UPDATE calls SET specialty='cardiology' WHERE id='old-call'")


def test_failed_migration_rolls_back_ddl_and_data(tmp_path):
    path = tmp_path / "corrupt.db"
    legacy_database(path)
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO provider_networks VALUES ('missing-provider','VALUE')")
    conn.commit()
    conn.close()
    db = Database(path)
    with pytest.raises(sqlite3.IntegrityError, match="foreign-key audit"):
        db.initialize()
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    assert "source" not in {
        row[1] for row in conn.execute("PRAGMA table_info(appointments)")
    }
    assert (
        conn.execute("SELECT confirmation FROM appointments").fetchone()[0]
        == "MG-APT-123456"
    )
    assert not conn.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE '%__v2'"
    ).fetchall()
    conn.close()


def test_reported_referral_can_record_unknown_pcp_but_cannot_be_verified(db):
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO referrals(id,member_id,specialty,status,source,created_at) "
            "VALUES ('reported','M4','cardiology','reported','caller_report','2026-11-06T21:00:00Z')"
        )
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
        conn.execute("UPDATE referrals SET status='verified' WHERE id='reported'")


def test_duplicate_replacement_link_is_rejected(db):
    manifest = seed(db, demo_date=date(2026, 11, 6), care_journeys=True)
    original = manifest["cases"][0]["appointment_id"]
    # Terminal history rows may share a slot; a lineage still has one successor.
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO appointments(id,member_id,provider_id,slot_id,confirmation,status,starts_at,ends_at,created_at,source,replaces_appointment_id) "
            "SELECT 'successor',member_id,provider_id,slot_id,'MG-DEMO-SUCCESSOR','rescheduled',starts_at,ends_at,created_at,'synthetic_fixture',id "
            "FROM appointments WHERE id=?",
            (original,),
        )
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
        conn.execute(
            "INSERT INTO appointments(id,member_id,provider_id,slot_id,confirmation,status,starts_at,ends_at,created_at,source,replaces_appointment_id) "
            "SELECT 'duplicate',member_id,provider_id,slot_id,'MG-DEMO-DUPLICATE','rescheduled',starts_at,ends_at,created_at,'synthetic_fixture',id "
            "FROM appointments WHERE id=?",
            (original,),
        )


def test_parallel_initializers_only_migrate_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / "parallel.db"
    legacy_database(path)
    barrier = Barrier(2)

    def initialize():
        barrier.wait()
        Database(path).initialize()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(initialize) for _ in range(2)]
        for future in futures:
            future.result()
    with Database(path).snapshot() as conn:
        assert conn.execute("SELECT count(*) FROM appointments").fetchone()[0] == 1
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
