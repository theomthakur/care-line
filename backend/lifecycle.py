"""Approved retention, authenticated encrypted backups, and recovery drills.

Run maintenance on the database host, under its service account. The database,
WAL, maintenance files and recovery targets must reside on an encrypted volume.
Backup keys and the current erasure ledger live outside the backup archive.
"""

import argparse
import fcntl
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from cryptography.fernet import Fernet, MultiFernet

from backend.core.common import instant, utc
from backend.core.db import Database
from backend.security import private_file, timestamp


@dataclass(frozen=True)
class RetentionPolicy:
    policy_id: str
    approved_by: str
    approved_at: str
    turns_days: int
    calls_days: int
    appointments_days: int
    summaries_days: int
    tasks_days: int
    backups_days: int

    @classmethod
    def load(cls, path):
        policy = cls(**json.loads(private_file(path)))
        if not policy.policy_id or not policy.approved_by:
            raise ValueError("Retention requires an approved policy reference")
        approved_at = timestamp(policy.approved_at)
        from datetime import datetime, timezone

        if approved_at > datetime.now(timezone.utc):
            raise ValueError("Retention approval cannot be in the future")
        days = [
            getattr(policy, field)
            for field in policy.__dataclass_fields__
            if field.endswith("_days")
        ]
        if any(type(day) is not int or day < 1 for day in days):
            raise ValueError("Retention periods must be positive whole days")
        if policy.calls_days < max(
            policy.appointments_days,
            policy.tasks_days,
            policy.summaries_days,
            policy.turns_days,
        ):
            raise ValueError("Call envelopes must outlive their dependent records")
        if policy.backups_days > min(days):
            raise ValueError(
                "Backup retention must not exceed the shortest record retention"
            )
        return policy


def delete_call(conn, call_id):
    conn.execute("UPDATE calls SET current_draft_id=NULL WHERE id=?", (call_id,))
    # Deleting historical appointments never reopens a time in the schedule.
    for table in (
        "appointments",
        "drafts",
        "turns",
        "events",
        "tasks",
        "identity_reviews",
        "call_access",
        "legal_holds",
    ):
        conn.execute(f"DELETE FROM {table} WHERE call_id=?", (call_id,))
    conn.execute("DELETE FROM calls WHERE id=?", (call_id,))


def apply_retention(db, policy):
    now = db.now()
    cutoff = lambda days: utc(now - timedelta(days=days))  # noqa: E731
    with db.transaction() as conn:
        # A dropped phone connection must not leave records immortal. Expire
        # abandoned call envelopes after the approved call inactivity period.
        conn.execute(
            "UPDATE calls SET status='finalized',finalized_at=COALESCE((SELECT MAX(received_at) FROM turns WHERE call_id=calls.id),created_at) WHERE status='live' AND id NOT IN (SELECT call_id FROM legal_holds) AND COALESCE((SELECT MAX(received_at) FROM turns WHERE call_id=calls.id),created_at)<?",
            (cutoff(policy.calls_days),),
        )
        eligible = "SELECT id FROM calls WHERE status='finalized' AND id NOT IN (SELECT call_id FROM legal_holds)"
        # Keep consent provenance rows until appointments expire, but remove raw
        # turn text on its own schedule. This includes assistant speech.
        conn.execute(
            "UPDATE turns SET text='[expired]' WHERE received_at<? AND call_id NOT IN (SELECT call_id FROM legal_holds)",
            (cutoff(policy.turns_days),),
        )
        conn.execute(
            f"UPDATE calls SET summary_json=NULL WHERE id IN ({eligible}) AND finalized_at<?",
            (cutoff(policy.summaries_days),),
        )
        conn.execute(
            f"DELETE FROM tasks WHERE call_id IN ({eligible}) AND created_at<?",
            (cutoff(policy.tasks_days),),
        )
        conn.execute(
            f"DELETE FROM appointments WHERE call_id IN ({eligible}) AND ends_at<?",
            (cutoff(policy.appointments_days),),
        )
        # Draft readbacks, request snapshots, and first_request can repeat raw
        # turns. Scrub them on the shortest applicable content schedule too.
        conn.execute(
            f"UPDATE calls SET first_request=NULL,providers_json='[]',excluded_json='[]',evidence_json='[]',offered_slots_json='[]',availability_query_json=NULL WHERE id IN ({eligible}) AND finalized_at<?",
            (cutoff(policy.turns_days),),
        )
        # Draft CHECK constraints require a non-null readback for booked rows.
        conn.execute(
            f"UPDATE drafts SET read_back='[expired]' WHERE call_id IN ({eligible}) AND created_at<? AND read_back IS NOT NULL",
            (cutoff(policy.turns_days),),
        )
        rows = conn.execute(
            f"SELECT id FROM calls WHERE id IN ({eligible}) AND finalized_at<? AND NOT EXISTS (SELECT 1 FROM appointments a WHERE a.call_id=calls.id)",
            (cutoff(policy.calls_days),),
        ).fetchall()
        for row in rows:
            delete_call(conn, row["id"])
    # SQLite secure_delete clears freed pages; WAL and old encrypted snapshots
    # still require their own lifecycle. Busy checkpoints are retried next run.
    conn = db.connect()
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


class Archive:
    def __init__(self, db, directory, key_file, ledger, policy):
        self.db, self.directory, self.ledger, self.policy = (
            db,
            Path(directory),
            Path(ledger),
            policy,
        )
        # New key first; retain old decryption keys only until old backups expire.
        self.cipher = MultiFernet(
            [Fernet(key.encode()) for key in json.loads(private_file(key_file))]
        )
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.ledger.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (
            self.directory.stat().st_mode & 0o077
            or self.ledger.parent.stat().st_mode & 0o077
        ):
            raise ValueError("Archive and ledger directories must be owner-only")

    @contextmanager
    def locked(self):
        # Coordinate retention, deletion, backup and restore, including separate
        # maintenance processes. API mutations still use SQLite transactions.
        fd = os.open(self.ledger.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def seal(self, path, payload):
        encrypted = self.cipher.encrypt(json.dumps(payload).encode())
        temporary = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def open(self, path):
        return json.loads(self.cipher.decrypt(path.read_bytes()))

    def erasures(self):
        # A missing current ledger must fail closed, including on recovery.
        payload = self.open(self.ledger)
        if (payload["organization"], payload["environment"]) != (
            self.db.organization,
            self.db.environment,
        ):
            raise ValueError("Erasure ledger scope mismatch")
        return payload

    def init_ledger(self):
        with self.locked():
            if self.ledger.exists():
                raise ValueError("Erasure ledger already exists")
            self.seal(
                self.ledger,
                {
                    "organization": self.db.organization,
                    "environment": self.db.environment,
                    "deletions": [],
                },
            )

    def erase(self, member_id, reference):
        if not reference or len(reference) > 128:
            raise ValueError("An approved deletion case reference is required")
        with self.locked(), self.db.transaction() as conn:
            payload = self.erasures()
            blocked = conn.execute(
                "SELECT 1 FROM calls c LEFT JOIN legal_holds h ON h.call_id=c.id WHERE c.member_id=? AND (c.status='live' OR h.call_id IS NOT NULL)",
                (member_id,),
            ).fetchone()
            if blocked:
                raise ValueError("Resolve live calls or legal holds before erasure")
            payload["deletions"].append(
                {
                    "member_id": member_id,
                    "reference": reference,
                    "at": utc(self.db.now()),
                }
            )
            # Durable tombstone precedes DB commit. On failure, replaying the
            # request or recovery completes deletion conservatively.
            self.seal(self.ledger, payload)
            for row in conn.execute(
                "SELECT id FROM calls WHERE member_id=?", (member_id,)
            ).fetchall():
                delete_call(conn, row["id"])
            conn.execute("DELETE FROM members WHERE id=?", (member_id,))

    def expire_backups(self):
        cutoff = self.db.now() - timedelta(days=self.policy.backups_days)
        for path in self.directory.glob("*.mgbackup"):
            payload = self.open(path)
            if (
                payload["organization"] != self.db.organization
                or payload["environment"] != self.db.environment
            ):
                raise ValueError("Backup scope mismatch")
            if instant(payload["created_at"]) < cutoff:
                path.unlink()

    def backup(self):
        from backend.core.common import identifier

        with self.locked():
            self.erasures()
            apply_retention(self.db, self.policy)
            with self.db.snapshot() as source:
                memory = sqlite3.connect(":memory:")
                try:
                    source.backup(memory)
                    sql = "\n".join(memory.iterdump())
                    schema_version = memory.execute("PRAGMA user_version").fetchone()[0]
                finally:
                    memory.close()
            path = self.directory / (identifier("backup") + ".mgbackup")
            self.seal(
                path,
                {
                    "organization": self.db.organization,
                    "environment": self.db.environment,
                    "created_at": utc(self.db.now()),
                    "policy": self.policy.policy_id,
                    "schema_version": schema_version,
                    "sql": sql,
                },
            )
            self.expire_backups()
            return path

    def restore(self, backup, target):
        with self.locked():
            payload, ledger = self.open(Path(backup)), self.erasures()
            if (payload["organization"], payload["environment"]) != (
                self.db.organization,
                self.db.environment,
            ):
                raise ValueError("Backup scope mismatch")
            if instant(payload["created_at"]) < self.db.now() - timedelta(
                days=self.policy.backups_days
            ):
                raise ValueError("Backup has expired")
            target = Path(target)
            if target.parent.stat().st_mode & 0o077:
                raise ValueError("Recovery directory must be owner-only and encrypted")
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            recovered = Database(target, clock=self.db.clock)
            recovered.environment, recovered.organization = (
                self.db.environment,
                self.db.organization,
            )
            try:
                conn = recovered.connect()
                try:
                    # Dump order contains circular FKs. Check every FK after load.
                    conn.execute("PRAGMA foreign_keys=OFF")
                    conn.executescript(payload["sql"])
                    version = payload.get("schema_version")
                    if version is None:
                        # Older SQL dumps did not include PRAGMA user_version.
                        columns = {
                            row["name"]
                            for row in conn.execute("PRAGMA table_info(plans)")
                        }
                        version = 2 if "specialist_referral_required" in columns else 1
                    if not isinstance(version, int) or version < 1:
                        raise ValueError("Invalid backup schema version")
                    conn.execute(f"PRAGMA user_version = {version}")
                    conn.execute("PRAGMA foreign_keys=ON")
                    if (
                        conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                        or conn.execute("PRAGMA foreign_key_check").fetchone()
                    ):
                        raise ValueError("Recovery integrity check failed")
                finally:
                    conn.close()
                recovered.initialize()  # Validate durable organization/environment.
                with recovered.transaction() as conn:
                    for deletion in ledger["deletions"]:
                        for row in conn.execute(
                            "SELECT id FROM calls WHERE member_id=?",
                            (deletion["member_id"],),
                        ).fetchall():
                            delete_call(conn, row["id"])
                        conn.execute(
                            "DELETE FROM members WHERE id=?", (deletion["member_id"],)
                        )
                apply_retention(recovered, self.policy)
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            return recovered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["init-ledger", "retain", "backup", "recover", "erase"]
    )
    parser.add_argument("--policy", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--keys", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--backup")
    parser.add_argument("--target")
    parser.add_argument("--member")
    parser.add_argument("--reference")
    args = parser.parse_args()
    policy = RetentionPolicy.load(args.policy)
    db = Database()
    db.initialize()
    archive = Archive(db, args.archive, args.keys, args.ledger, policy)
    if args.action == "init-ledger":
        archive.init_ledger()
    elif args.action == "backup":
        archive.backup()
    elif args.action == "retain":
        with archive.locked():
            apply_retention(db, policy)
            archive.expire_backups()
    elif args.action == "erase":
        if not args.member or not args.reference:
            parser.error("erase requires --member and --reference")
        archive.erase(args.member, args.reference)
    else:
        if not args.backup or not args.target:
            parser.error("recover requires --backup and --target")
        archive.restore(args.backup, args.target)
    print("Maintenance completed; record the recovery result in deployment evidence.")


if __name__ == "__main__":
    main()
