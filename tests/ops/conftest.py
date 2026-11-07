"""Ops test harness: a temp SQLite database built from contracts/schema.sql, a frozen
clock (the contract examples freeze at 2026-11-06 4 PM Eastern), and a tiny ASGI caller
so route tests need no extra dependency."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.db import Database  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.ops import clock  # noqa: E402
from backend.ops.db import connect  # noqa: E402
from backend.ops.dev_seed import build_stage, init_db  # noqa: E402
from backend.security import digest  # noqa: E402
from tests.security_helpers import TOKENS, configure_roles  # noqa: E402

CALL_START = datetime(2026, 11, 6, 21, 0, 0, tzinfo=timezone.utc)  # 4:00 PM Eastern
EXAMPLES = ROOT / "contracts" / "examples"


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(
        clock, "now", lambda: datetime(2026, 11, 6, 21, 0, 50, tzinfo=timezone.utc)
    )


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "ops.db"
    init_db(p, now=CALL_START).close()
    return p


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def stage(conn):
    def _stage(name: str):
        result = build_stage(conn, name, base=CALL_START)
        conn.execute(
            "INSERT INTO call_access VALUES ('c_01','development-agent',?)",
            (digest("ops-test-call-capability-at-least-32-characters"),),
        )
        return result

    return _stage


@pytest.fixture
def app(db_path):
    db = Database(db_path)
    db.initialize()
    a = create_app(database=db, agent_key="dev-agent-key")
    configure_roles(a, db_path.parent / "credentials.json")
    return a


def asgi_caller(app):
    """Minimal ASGI client so route tests need no extra dependency."""

    async def _call(method: str, path: str, body=None, headers=None):
        if headers is None and not path.endswith(("/followup", "/finalize")):
            role = "admin" if path.startswith("/admin/") else "operator"
            headers = {"Authorization": "Bearer " + TOKENS[role]}
        if headers and "X-Agent-Key" in headers:
            headers = {
                **headers,
                "X-Call-Key": "ops-test-call-capability-at-least-32-characters",
            }
        raw = b"" if body is None else json.dumps(body).encode()
        hdrs = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(raw)).encode()),
        ]
        hdrs += [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
        path_only, _, query = path.partition("?")
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "path": path_only,
            "raw_path": path_only.encode(),
            "query_string": query.encode(),
            "headers": hdrs,
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 1),
            "root_path": "",
        }
        sent = {"done": False}

        async def receive():
            if not sent["done"]:
                sent["done"] = True
                return {"type": "http.request", "body": raw, "more_body": False}
            return {"type": "http.disconnect"}

        out = {"status": 0, "body": b""}

        async def send(msg):
            if msg["type"] == "http.response.start":
                out["status"] = msg["status"]
            elif msg["type"] == "http.response.body":
                out["body"] += msg.get("body", b"")

        await app(scope, receive, send)
        return out["status"], json.loads(out["body"] or b"null")

    return _call


@pytest.fixture
def call(app):
    return asgi_caller(app)
