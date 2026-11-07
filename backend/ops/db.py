"""Connection helpers. Only the backend process opens the database (schema.sql header)."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import Request

DEFAULT_DB = Path(os.getenv("CARELINE_DB", "data/memberguide.db"))


def connect(path: str | Path) -> sqlite3.Connection:
    """Autocommit connection: transactions are explicit (BEGIN / BEGIN IMMEDIATE)."""
    conn = sqlite3.connect(
        str(path), isolation_level=None, timeout=5.0, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def open_conn(state) -> sqlite3.Connection:
    """A connection for the host app's database (``app.state`` as set by core or the dev app)."""
    shared = getattr(state, "db", None)  # core's Database
    factory = getattr(state, "get_conn", None)
    if shared is not None and hasattr(shared, "path"):
        # Same file, our own connection: handlers run across threads, and core's
        # POST ingress middleware already serialises every write request.
        return connect(shared.path)
    if factory:
        return factory()
    return connect(getattr(state, "db_path", DEFAULT_DB))


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """FastAPI dependency. The host app may set ``app.state.db_path`` (or ``app.state.get_conn``)."""
    conn = open_conn(request.app.state)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def immediate(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE ... COMMIT/ROLLBACK (reuses an open transaction if there is one)."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
