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
DEFAULT_PATH = ROOT / "data" / "synthetic" / "memberguide.db"


class Database:
    def __init__(self, path=None, *, clock=None, timeout=5):
        self.path = Path(path or os.environ.get("MEMBERGUIDE_DB_PATH") or DEFAULT_PATH)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.timeout = timeout
        # One live call per member. Off for library use, on for the running service.
        self.one_call_per_member = False
        self.environment = os.getenv("MEMBERGUIDE_ENV", "synthetic")
        self.organization = os.getenv("MEMBERGUIDE_ORGANIZATION", "synthetic")
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
        conn.execute("PRAGMA secure_delete = ON")
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
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink() or self.path.parent.stat().st_mode & 0o077:
            raise ValueError(
                "Database must use an owner-only directory and a regular file"
            )
        # Set file permissions before SQLite writes any records or sidecars.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self._write_barrier():
            conn = self.connect()
            try:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("BEGIN IMMEDIATE")
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='calls'"
                ).fetchone()
                if not exists:
                    # Execute complete statements without executescript's implicit COMMIT.
                    statement = ""
                    for line in (
                        (ROOT / "contracts" / "schema.sql").read_text().splitlines(True)
                    ):
                        statement += line
                        if sqlite3.complete_statement(statement):
                            conn.execute(statement)
                            statement = ""
                for statement in (
                    (ROOT / "backend" / "security_schema.sql").read_text().split(";")
                ):
                    if statement.strip():
                        conn.execute(statement)
                scope = conn.execute("SELECT * FROM deployment_scope").fetchone()
                if scope is None:
                    # Never silently relabel an existing synthetic/legacy DB as production.
                    if exists and self.environment == "production":
                        raise ValueError(
                            "Production requires a new, separately provisioned database"
                        )
                    conn.execute(
                        "INSERT INTO deployment_scope VALUES (1,?,?)",
                        (self.organization, self.environment),
                    )
                elif (scope["organization"], scope["environment"]) != (
                    self.organization,
                    self.environment,
                ):
                    raise ValueError("Database organization/environment mismatch")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
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
