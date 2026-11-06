"""HTTP integration of the voice adapter with the actual booking service."""

import asyncio
import socket
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
import uvicorn

from backend.core.db import Database
from backend.main import create_app
from backend_client import BackendUnavailableError, HttpBackend
from fake_backend import FakeBackend
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
async def core(tmp_path):
    clock = Clock()
    db = Database(tmp_path / "test.db", clock=clock)
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
    client = HttpBackend(f"http://127.0.0.1:{port}", "test-key")
    yield client, clock, db
    await client.close()
    server.should_exit = True
    await asyncio.wait_for(task, 5)


async def ready(core, provider="P2", day="2026-11-13"):
    client, clock, db = core
    flow = Flow(client)
    await flow.start("voice-integration")
    assert "verified" in (await flow.verify("4417", "April")).lower()
    await flow.record_user_turn("I want a primary care doctor.")
    assert "Haddad" in await flow.find_providers("primary care", "10023")
    result = await flow.find_slots(provider, day, "afternoon")
    assert "Slot ids" in result, result
    with db.snapshot() as conn:
        row = conn.execute(
            "SELECT selected_provider_id, offered_slots_json FROM calls WHERE id=?",
            (flow.call_id,),
        ).fetchone()
        import json

        slots = json.loads(row["offered_slots_json"])
        assert row["selected_provider_id"] == provider
    assert await flow.prepare(slots[0]["slot_id"], lambda _: Speech()) is None
    clock.now += timedelta(seconds=1)
    await flow.record_user_turn("yes")
    return flow


@pytest.mark.asyncio
async def test_real_http_selects_p4_and_confirms_nested_response(core):
    flow = await ready(core, "P4", "2026-11-11")
    answer = await flow.confirm()
    assert flow.booked and "booked" in answer.lower()
    assert "simulated" in answer.lower()
    await flow.finalize()
    await flow.backend.close()


@pytest.mark.asyncio
async def test_real_http_lost_confirmation_response_replays_same_token(core):
    flow = await ready(core)
    client, _, db = core
    original = client.confirm
    attempts = []

    async def lost_response(call_id, token):
        result = await original(call_id, token)
        attempts.append(token)
        if len(attempts) == 1:
            raise BackendUnavailableError("response lost after commit")
        return result

    client.confirm = lost_response
    answer = await flow.confirm()
    assert flow.booked and "booked" in answer.lower()
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    with db.snapshot() as conn:
        assert conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_failed_turn_response_disarms_and_blocks_older_yes():
    backend = FakeBackend()
    flow = Flow(backend)
    await flow.start("failed-turn")
    flow.armed, flow.token = True, "old"

    async def reject(*args):
        return {"ok": False, "error": "FAIL"}

    backend.turn = reject
    with pytest.raises(BackendUnavailableError):
        await flow.record_user_turn("No, change it")
    assert flow.armed is False and flow.token is None
    assert "NOT ARMED" in await flow.confirm()


@pytest.mark.asyncio
async def test_speech_begins_during_readback_but_finishes_after_arm(core):
    client, _, db = core
    flow = Flow(client)
    await flow.start("overlap")
    await flow.verify("4417", "April")
    await flow.find_providers("primary care", "10023")
    await flow.find_slots("P2", "2026-11-13", "afternoon")
    with db.snapshot() as conn:
        import json

        row = conn.execute(
            "SELECT offered_slots_json FROM calls WHERE id=?", (flow.call_id,)
        ).fetchone()
        slot = json.loads(row[0])[0]["slot_id"]
    original = client.armed
    speech = {"started": False}

    async def arm_while_speech_begins(call_id, token):
        result = await original(call_id, token)
        speech["started"] = True  # no final transcription has arrived
        return result

    client.armed = arm_while_speech_begins
    result = await flow.prepare(slot, lambda _: Speech(), lambda: speech["started"])
    assert "NOT ARMED" in result
    assert flow.armed is False and flow.token is None
    assert "NOT ARMED" in await flow.confirm()
    with db.snapshot() as conn:
        assert conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_turn_retry_uses_the_same_id():
    client = HttpBackend("http://127.0.0.1:1", "test-key")
    calls = []

    async def post(path, payload):
        calls.append(dict(payload))
        if len(calls) == 1:
            raise BackendUnavailableError("lost response")
        return {"ok": True, "turn_seq": 1}

    client._post = post
    assert (await client.turn("call", "user", "yes"))["ok"]
    assert len(calls) == 2 and calls[0]["client_turn_id"] == calls[1]["client_turn_id"]


@pytest.mark.asyncio
async def test_core_ops_followup_and_finalize_share_database(core):
    client, _, db = core
    started = await client.start_call("handoff-integration")
    cid = started["call_id"]
    result = await client.followup(
        cid, "caller_requested", "Please have someone call me."
    )
    assert result["ok"] and result["task"]["packet"]["reference"]
    finished = await client.finalize(cid)
    assert finished["ok"] and finished["summary"]["outcome"] == "followup"
    with db.snapshot() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM tasks WHERE call_id=?", (cid,)
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute("SELECT status FROM calls WHERE id=?", (cid,)).fetchone()[0]
            == "finalized"
        )


@pytest.mark.asyncio
async def test_failed_new_turn_over_real_http_disarms_prior_yes(core):
    flow = await ready(core)
    client, _, db = core
    client._http().headers["X-Agent-Key"] = "wrong-key"
    with pytest.raises(BackendUnavailableError):
        await flow.record_user_turn("No, choose a different day")
    client._http().headers["X-Agent-Key"] = "test-key"
    assert flow.armed is False and flow.token is None
    assert "NOT ARMED" in await flow.confirm()
    with db.snapshot() as conn:
        assert conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_earliest_availability_uses_core_clock_and_any_period(core):
    client, _, _ = core
    flow = Flow(client)
    await flow.start("earliest-real")
    await flow.verify("4417", "April")
    await flow.find_providers("primary care", "10023")
    answer = await flow.find_slots("P2", "earliest available", "")
    assert "Slot ids" in answer
    assert "NOT" not in answer


@pytest.mark.asyncio
async def test_lost_responses_reconcile_call_scoped_appointment_without_token(core):
    flow = await ready(core)
    client, _, db = core
    original = client.confirm
    count = 0

    async def lost_responses(call_id, token):
        nonlocal count
        count += 1
        if count == 1:
            await original(call_id, token)
        raise BackendUnavailableError("response unavailable")

    client.confirm = lost_responses
    answer = await flow.confirm()
    assert flow.booked and "booked" in answer.lower()
    assert count == 2
    with db.snapshot() as conn:
        assert conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 1
