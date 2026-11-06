"""Two concurrent phone sessions (real Flow objects over real HTTP) sharing one core
backend and one SQLite database must never share state: transcript, verification,
booking, handoff task and finalize are all scoped to the caller's own call id."""

import asyncio
import json
import socket
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
import uvicorn

from backend.core.db import Database
from backend.main import create_app
from backend_client import HttpBackend
from flow import Flow


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 6, 21, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class Speech:
    interrupted = False

    async def wait_for_playout(self):
        return None


@pytest_asyncio.fixture
async def service(tmp_path):
    clock = Clock()
    db = Database(tmp_path / "multi.db", clock=clock)
    app = create_app(database=db, agent_key="test-key")
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.02)
    assert server.started
    # one HttpBackend per session, exactly as make_backend() builds them per call
    clients = []

    def session():
        c = HttpBackend(f"http://127.0.0.1:{port}", "test-key")
        clients.append(c)
        return Flow(c)

    yield session, clock, db
    for c in clients:
        await c.close()
    server.should_exit = True
    await asyncio.wait_for(task, 5)


def rows(db, sql, *args):
    with db.snapshot() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


@pytest.mark.asyncio
async def test_concurrent_sessions_are_isolated_end_to_end(service):
    session, clock, db = service
    a, b = session(), session()
    await asyncio.gather(a.start("call-room-A"), b.start("call-room-B"))
    assert a.call_id and b.call_id and a.call_id != b.call_id

    # verification, interleaved: each call binds to its own member
    await asyncio.gather(
        a.record_user_turn("A-ONLY four four one seven"),
        b.record_user_turn("B-ONLY two two six one"),
    )
    ra, rb = await asyncio.gather(a.verify("4417", "April"), b.verify("2261", "June"))
    assert "verified" in ra.lower() and "verified" in rb.lower()
    members = {
        r["id"]: r["member_id"] for r in rows(db, "SELECT id, member_id FROM calls")
    }
    assert members[a.call_id] != members[b.call_id]
    assert {members[a.call_id], members[b.call_id]} == {
        r["id"]
        for r in rows(
            db, "SELECT id FROM members WHERE member_digits IN ('4417','2261')"
        )
    }

    # A books while B is still on the phone and asks for a person
    await a.record_user_turn("A-ONLY I want a primary care doctor")
    await b.record_user_turn("B-ONLY please have someone call me")
    assert "Haddad" in await a.find_providers("primary care", "10023")
    result = await a.find_slots("P2", "2026-11-13", "afternoon")
    assert "Slot ids" in result, result
    offered = json.loads(
        rows(db, "SELECT offered_slots_json FROM calls WHERE id=?", a.call_id)[0][
            "offered_slots_json"
        ]
    )
    assert await a.prepare(offered[0]["slot_id"], lambda _: Speech()) is None
    clock.now += timedelta(seconds=1)
    await a.record_user_turn("yes")
    followup = await b.followup("caller_requested", "B-ONLY wants a callback")
    confirmed = await a.confirm()
    assert "booked" in confirmed.lower() or "confirmation" in confirmed.lower(), (
        confirmed
    )

    # every row belongs to exactly one call
    appts = rows(db, "SELECT call_id FROM appointments")
    assert [x["call_id"] for x in appts] == [a.call_id]
    tasks = rows(db, "SELECT call_id FROM tasks")
    assert [x["call_id"] for x in tasks] == [b.call_id] and followup
    for flow, mine, other in ((a, "A-ONLY", "B-ONLY"), (b, "B-ONLY", "A-ONLY")):
        own = [
            r["text"]
            for r in rows(db, "SELECT text FROM turns WHERE call_id=?", flow.call_id)
        ]
        assert own and all(other not in t for t in own)
        assert any(mine in t for t in own)
    assert rows(db, "SELECT call_id FROM drafts WHERE status='booked'") == [
        {"call_id": a.call_id}
    ]
    assert rows(db, "SELECT selected_provider_id FROM calls WHERE id=?", b.call_id) == [
        {"selected_provider_id": None}
    ]

    # finalizing A leaves B live
    await a.finalize()
    status = {r["id"]: r["status"] for r in rows(db, "SELECT id, status FROM calls")}
    assert status == {a.call_id: "finalized", b.call_id: "live"}
    await b.finalize()
    summaries = {
        r["id"]: json.loads(r["summary_json"])["outcome"]
        for r in rows(db, "SELECT id, summary_json FROM calls")
    }
    assert summaries == {a.call_id: "booked", b.call_id: "followup"}


@pytest.mark.asyncio
async def test_same_room_is_one_call_but_different_rooms_never_collide(service):
    session, _, _ = service
    first, replay, other = session(), session(), session()
    await asyncio.gather(
        first.start("call-room-1"),
        replay.start("call-room-1"),
        other.start("call-room-2"),
    )
    assert first.call_id == replay.call_id  # the room is the idempotency key
    assert other.call_id != first.call_id  # a new real call uses a new room
