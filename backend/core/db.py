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


class Database:
    def __init__(self, path=None, *, clock=None, timeout=5):
        self.path = Path(path or os.environ.get("MEMBERGUIDE_DB_PATH", DEFAULT_PATH))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.timeout = timeout
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
