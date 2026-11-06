"""The single connection factory and write barrier for core and ops.

Use app.state.db.transaction() for ALL writes, snapshot() for consistent reads.
Never share a sqlite connection across requests or await inside either context.
"""

import os
import sqlite3
import threading
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .errors import DomainError

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "data" / "memberguide.db"
SCHEMA_VERSION = 2


def schema_statements():
    statement = ""
    for line in (ROOT / "contracts" / "schema.sql").read_text().splitlines(True):
        # Comments are not needed for execution or migration table matching.
        if line.lstrip().startswith("--"):
            continue
        statement += line
        if sqlite3.complete_statement(statement):
            yield statement.strip()
            statement = ""


def migrate_v1(conn, statements):
    """Rebuild constrained tables using v2 DDL; preserve all existing values.

    Foreign keys must be disabled BEFORE BEGIN, then audited before COMMIT.
    Avoid renaming the old tables: SQLite would rewrite dependent FK targets.
    """
    for table in ("plans", "calls", "drafts", "appointments"):
        ddl = next(s for s in statements if s.startswith(f"CREATE TABLE {table} ("))
        replacement = f"{table}__v2"
        conn.execute(
            ddl.replace(f"CREATE TABLE {table}", f"CREATE TABLE {replacement}", 1)
        )
        columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
        column_list = ",".join(f'"{name}"' for name in columns)
        conn.execute(
            f"INSERT INTO {replacement} ({column_list}) SELECT {column_list} FROM {table}"
        )
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {replacement} RENAME TO {table}")
    conn.execute("UPDATE plans SET specialist_referral_required=0 WHERE id='GOLD'")
    for statement in statements:
        if statement.startswith(
            ("CREATE TABLE referrals (", "CREATE TABLE demo_fixture_sets (")
        ):
            conn.execute(statement)
        elif statement.startswith("CREATE INDEX "):
            conn.execute(
                statement.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)
            )
        elif statement.startswith("CREATE UNIQUE INDEX "):
            conn.execute(
                statement.replace(
                    "CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ", 1
                )
            )


class Database:
    def __init__(self, path=None, *, clock=None, timeout=5):
        self.path = Path(path or os.environ.get("MEMBERGUIDE_DB_PATH", DEFAULT_PATH))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.timeout = timeout
        # One live call per member. Off for library use, on for the running service.
        self.one_call_per_member = False
        self._condition = threading.Condition()
        self._queue = deque()

    def now(self):
        value = self.clock()
        if value.tzinfo is None:
            raise ValueError("Database clock must be timezone aware")
        return value.astimezone(timezone.utc)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {int(self.timeout * 1000)}")
        return conn

    @contextmanager
    def _write_barrier(self):
        ticket = object()
        with self._condition:
            self._queue.append(ticket)
            ready = self._condition.wait_for(
                lambda: self._queue[0] is ticket, timeout=self.timeout
            )
            if not ready:
                self._queue.remove(ticket)
                self._condition.notify_all()
                raise DomainError("SERVICE_UNAVAILABLE")
        try:
            yield
        finally:
            with self._condition:
                self._queue.popleft()
                self._condition.notify_all()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_barrier():
            conn = self.connect()
            try:
                conn.execute("PRAGMA journal_mode = WAL")
                # Required for SQLite's table-rebuild migration with circular FKs.
                # This connection is private and initialization holds the writer lock.
                conn.execute("PRAGMA foreign_keys = OFF")
                conn.execute("BEGIN IMMEDIATE")
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise RuntimeError(
                        f"Database schema {version} is newer than this backend"
                    )
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='calls'"
                ).fetchone()
                statements = list(schema_statements())
                if not exists:
                    for statement in statements:
                        # Connection settings must not change in a transaction.
                        if not statement.startswith("PRAGMA"):
                            conn.execute(statement)
                elif version < SCHEMA_VERSION:
                    migrate_v1(conn, statements)
                if conn.execute("PRAGMA foreign_key_check").fetchone():
                    raise sqlite3.IntegrityError(
                        "Database migration failed foreign-key audit"
                    )
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.execute("PRAGMA foreign_keys = ON")
                conn.close()

    @contextmanager
    def transaction(self):
        with self._write_barrier():
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except DomainError as exc:
                if exc.persist:
                    conn.commit()
                else:
                    conn.rollback()
                raise
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()

    @contextmanager
    def snapshot(self):
        conn = self.connect()
        try:
            conn.execute("BEGIN")
            yield conn
        finally:
            conn.rollback()
            conn.close()
