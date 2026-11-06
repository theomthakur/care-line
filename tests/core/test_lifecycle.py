import json
from dataclasses import asdict

import pytest
from cryptography.fernet import Fernet, InvalidToken

from backend.core.booking import confirm_booking
from backend.core.common import utc
from backend.credentials import write_private
from backend.lifecycle import Archive, RetentionPolicy, apply_retention
from tests.core.test_booking import consent, prepare


@pytest.fixture
def policy():
    return RetentionPolicy(
        "test-only-policy", "test-approver", "2026-01-01T00:00:00Z", 3, 30, 14, 5, 7, 2
    )


@pytest.fixture
def archive(db, tmp_path, policy):
    keys = tmp_path / "keys"
    write_private(keys, json.dumps([Fernet.generate_key().decode()]))
    result = Archive(db, tmp_path / "backups", keys, tmp_path / "erasures", policy)
    result.init_ledger()
    return result


def booked_call(db, clock):
    call_id, token = prepare(db)
    consent(db, clock, call_id)
    confirm_booking(db, call_id, token)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE calls SET status='finalized', finalized_at=?,first_request='private request',summary_json=? WHERE id=?",
            (utc(db.now()), json.dumps({"text": "private summary"}), call_id),
        )
    return call_id


def test_backup_is_encrypted_and_recovery_preserves_consistent_booking(
    archive, db, clock, tmp_path
):
    call_id = booked_call(db, clock)
    path = archive.backup()
    assert b"Maya" not in path.read_bytes() and b"CREATE TABLE" not in path.read_bytes()
    assert path.stat().st_mode & 0o077 == 0
    restored = archive.restore(path, tmp_path / "recovered.db")
    with restored.snapshot() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchone()
        assert (
            conn.execute(
                "SELECT member_id FROM appointments WHERE call_id=?", (call_id,)
            ).fetchone()[0]
            == "M1"
        )
    with pytest.raises(FileExistsError):
        archive.restore(path, restored.path)


def test_tampered_backup_cannot_be_restored(archive, tmp_path):
    path = archive.backup()
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 1
    path.write_bytes(data)
    with pytest.raises(InvalidToken):
        archive.restore(path, tmp_path / "tampered.db")
    assert not (tmp_path / "tampered.db").exists()


def test_retention_scrubs_raw_content_without_breaking_consent_provenance(
    db, clock, policy
):
    call_id = booked_call(db, clock)
    clock.advance(6 * 86400)
    apply_retention(db, policy)
    with db.snapshot() as conn:
        assert (
            conn.execute(
                "SELECT text FROM turns WHERE call_id=?", (call_id,)
            ).fetchone()[0]
            == "[expired]"
        )
        assert (
            conn.execute(
                "SELECT read_back FROM drafts WHERE call_id=?", (call_id,)
            ).fetchone()[0]
            == "[expired]"
        )
        call = conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        assert call["summary_json"] is None and call["first_request"] is None
        assert conn.execute(
            "SELECT 1 FROM appointments WHERE call_id=?", (call_id,)
        ).fetchone()
        assert not conn.execute("PRAGMA foreign_key_check").fetchone()
    clock.advance(40 * 86400)
    apply_retention(db, policy)
    with db.snapshot() as conn:
        for table in (
            "calls",
            "turns",
            "drafts",
            "appointments",
            "events",
            "call_access",
            "identity_reviews",
        ):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_legal_hold_prevents_retention_and_patient_erasure(archive, db, clock, policy):
    call_id = booked_call(db, clock)
    with db.transaction() as conn:
        conn.execute("INSERT INTO legal_holds VALUES (?,?)", (call_id, "test-hold"))
    clock.advance(90 * 86400)
    apply_retention(db, policy)
    with pytest.raises(ValueError, match="holds"):
        archive.erase("M1", "approved-case-test")
    with db.snapshot() as conn:
        assert (
            conn.execute(
                "SELECT text FROM turns WHERE call_id=?", (call_id,)
            ).fetchone()[0]
            == "yes"
        )


def test_erasure_is_replayed_into_older_backups(archive, db, clock, tmp_path):
    booked_call(db, clock)
    clock.advance(2 * 86400)
    path = archive.backup()
    archive.erase("M1", "approved-case-test")
    with db.snapshot() as conn:
        assert not conn.execute("SELECT 1 FROM members WHERE id='M1'").fetchone()
    restored = archive.restore(path, tmp_path / "after-erasure.db")
    with restored.snapshot() as conn:
        assert not conn.execute("SELECT 1 FROM members WHERE id='M1'").fetchone()
        assert not conn.execute("SELECT 1 FROM appointments").fetchone()
    archive.ledger.unlink()
    with pytest.raises(FileNotFoundError):
        archive.restore(path, tmp_path / "missing-ledger.db")


def test_expired_backups_are_deleted_by_authenticated_creation_time(
    archive, db, clock, tmp_path
):
    path = archive.backup()
    clock.advance(3 * 86400)
    with pytest.raises(ValueError, match="expired"):
        archive.restore(path, tmp_path / "expired.db")
    archive.backup()
    assert not path.exists()
    assert len(list(archive.directory.glob("*.mgbackup"))) == 1


def test_policy_must_have_approval_and_compatible_periods(tmp_path, policy):
    path = tmp_path / "policy"
    for changes in (
        {"approved_by": ""},
        {"turns_days": 0},
        {"turns_days": True},
        {"backups_days": 10},
        {"calls_days": 2},
    ):
        write_private(path, json.dumps({**asdict(policy), **changes}))
        with pytest.raises(ValueError):
            RetentionPolicy.load(path)
    write_private(path, json.dumps(asdict(policy)))
    assert RetentionPolicy.load(path) == policy


def test_recovery_runs_current_retention_policy_and_checks_scope(
    archive, db, clock, tmp_path
):
    booked_call(db, clock)
    clock.advance(2 * 86400)
    path = archive.backup()
    # Turns predate the backup; they must expire before this snapshot is served.
    clock.advance(2 * 86400)
    restored = archive.restore(path, tmp_path / "new-policy.db")
    with restored.snapshot() as conn:
        assert conn.execute("SELECT text FROM turns").fetchone()[0] == "[expired]"
    db.organization = "another-org"
    with pytest.raises(ValueError, match="scope"):
        archive.restore(path, tmp_path / "wrong-scope.db")
