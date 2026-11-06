"""Local synthetic preview; the team backend and live voice are not connected."""

import asyncio
import hmac
import json
import os
import sys
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fake_backend import FakeBackend

backend = FakeBackend()
state = {"call_id": None, "providers": [], "excluded": [], "slots": [], "events": []}
lock = asyncio.Lock()
live_calls: set[str] = set()  # started by the voice agent and not yet finalized


def _busy():
    """Reset and sample replace the whole store, so never while a real call is live."""
    return web.json_response(
        {
            "error": "CALL_ACTIVE",
            "speak": "A call is in progress. Reset is refused. Add ?force=1 only if the call is stuck.",
        },
        status=409,
    )


def snapshot():
    cid = state["call_id"]
    call = backend.calls.get(cid, {})
    return {
        "call_id": cid,
        "verified": bool(call.get("member")),
        "member": "Maya Torres" if call.get("member") else None,
        "plan": "Gold 2026" if call.get("member") else None,
        "providers": state["providers"],
        "excluded": state["excluded"],
        "slots": state["slots"],
        "events": state["events"],
        "transcript": [
            {"role": t["role"], "text": t["text"]}
            for t in call.get("turns", [])
            if t["role"] in ("user", "assistant")
        ],
        "appointment": next(
            (
                {"confirmation": a["confirmation"], "description": a["speak"]}
                for a in backend.appointments
                if call.get("draft") and a.get("token") == call["draft"].get("token")
            ),
            None,
        ),
    }


async def index(request):
    return web.FileResponse(Path(__file__).with_name("index.html"))


async def status(request):
    async with lock:
        return web.json_response(snapshot())


async def sample(request):
    global backend, state
    if live_calls and request.query.get("force") != "1":
        return _busy()
    async with lock:
        live_calls.clear()
        backend = FakeBackend()
        state = {
            "call_id": None,
            "providers": [],
            "excluded": [],
            "slots": [],
            "events": [],
        }
        cid = (await backend.start_call("local-sample"))["call_id"]
        state["call_id"] = cid
        await backend.verify(cid, "4417", "april")
        result = await backend.providers(cid, "primary care", "10019")
        state["providers"] = result.get("providers", [])
        state["excluded"] = result.get("excluded", [])
        state["events"] = [
            "Sample call started",
            "Sample member verified",
            "In-network primary care options found",
        ]
        return web.json_response(snapshot())


async def options(request):
    async with lock:
        cid = state["call_id"]
        if not cid:
            return web.json_response({"error": "Load the sample first."}, status=400)
        pid = (await request.json()).get("provider_id", "")
        selected = await backend.select(cid, pid)
        if not selected.get("ok"):
            return web.json_response(
                {"error": "Please choose a listed provider."}, status=400
            )
        from datetime import timedelta

        today = backend.now.date()
        result = await backend.availability(
            cid, pid, today.isoformat(), (today + timedelta(days=14)).isoformat(), "any"
        )
        state["slots"] = result.get("slots", [])
        state["events"].append("Checked sample availability")
        return web.json_response(snapshot())


async def reset(request):
    global backend, state
    if live_calls and request.query.get("force") != "1":
        return _busy()
    async with lock:
        live_calls.clear()
        backend = FakeBackend()
        state = {
            "call_id": None,
            "providers": [],
            "excluded": [],
            "slots": [],
            "events": [],
        }
        return web.json_response(snapshot())


async def agent_route(request):
    """Single-process synthetic service used by the voice agent and local console."""
    if not hmac.compare_digest(
        request.headers.get("X-Agent-Key", ""), os.getenv("AGENT_KEY", "dev-agent-key")
    ):
        return web.json_response(
            {"error": "UNAUTHORIZED", "speak": "The system is unavailable."}, status=401
        )
    try:
        body = await request.json() if request.can_read_body else {}
    except (ValueError, json.JSONDecodeError):
        return web.json_response(
            {"error": "INVALID_REQUEST", "speak": "Please try again."}, status=400
        )
    async with lock:
        cid = request.match_info.get("cid")
        path = request.match_info.get("action", "")
        if not cid:
            r = await backend.start_call(str(body.get("room", "demo"))[:200])
            state.update(
                call_id=r["call_id"],
                providers=[],
                excluded=[],
                slots=[],
                events=["Call started"],
            )
            live_calls.add(r["call_id"])
            return web.json_response(r)
        if cid not in backend.calls:
            return web.json_response(
                {"error": "UNKNOWN_CALL", "speak": "Please try again."}, status=404
            )
        c = backend.calls[cid]
        if path in (
            "availability",
            "slot",
            "appointment/preview",
            "appointment/armed",
            "appointment/confirm",
            "appointment",
        ) and not c.get("member"):
            return web.json_response(
                {
                    "ok": False,
                    "error": "VERIFICATION_REQUIRED",
                    "speak": "I need to verify you first.",
                }
            )
        try:
            if path == "verify":
                r = await backend.verify(
                    cid,
                    str(body.get("member_digits", "")),
                    str(body.get("birth_month", "")),
                )
                if r.get("ok"):
                    state["events"].append("Sample member verified")
            elif path == "turn":
                role = body.get("role")
                if role not in ("user", "assistant"):
                    raise ValueError("Invalid role")
                r = await backend.turn(cid, role, str(body.get("text", ""))[:4000])
            elif path == "providers":
                r = await backend.providers(
                    cid, str(body.get("specialty", "")), str(body.get("zip", ""))
                )
                state["providers"], state["excluded"], state["slots"] = (
                    r.get("providers", []),
                    r.get("excluded", []),
                    [],
                )
                if r.get("ok"):
                    state["events"].append("Checked in-network care options")
            elif path == "select":
                r = await backend.select(cid, str(body.get("provider_id", "")))
            elif path == "dates":
                r = await backend.dates(cid, str(body.get("text", "")))
            elif path == "availability":
                pid = str(body.get("provider_id", ""))
                if pid != c.get("selected"):
                    return web.json_response(
                        {
                            "ok": False,
                            "error": "UNKNOWN_PROVIDER",
                            "speak": "Please choose a provider first.",
                        }
                    )
                r = await backend.availability(
                    cid,
                    pid,
                    str(body.get("date_from", "")),
                    str(body.get("date_to", "")),
                    str(body.get("part_of_day", "")),
                )
                state["slots"] = r.get("slots", [])
            elif path == "slot":
                r = await backend.slot(cid, str(body.get("slot_id", "")))
            elif path == "appointment/preview":
                r = await backend.preview(cid)
            elif path == "appointment/armed":
                r = await backend.armed(cid, str(body.get("token", "")))
            elif path == "appointment/confirm":
                r = await backend.confirm(cid, str(body.get("token", "")))
                if (
                    r.get("ok")
                    and "Sample appointment confirmed" not in state["events"]
                ):
                    state["events"].append("Sample appointment confirmed")
            elif path == "followup":
                r = await backend.followup(
                    cid,
                    str(body.get("category", ""))[:80],
                    str(body.get("detail", ""))[:1000],
                )
                state["events"].append("Follow-up request recorded: " + r["reference"])
            elif path == "appointment":
                r = await backend.appointment(cid)
            elif path == "finalize":
                r = await backend.finalize(cid)
                live_calls.discard(cid)
                state["events"].append("Call ended")
            else:
                return web.json_response(
                    {"error": "NOT_FOUND", "speak": "The system is unavailable."},
                    status=404,
                )
        except (ValueError, TypeError, KeyError):
            return web.json_response(
                {
                    "error": "INVALID_REQUEST",
                    "speak": "I could not complete that request.",
                },
                status=400,
            )
        return web.json_response(r)


app = web.Application()
app.add_routes(
    [
        web.get("/", index),
        web.get("/api/preview", status),
        web.post("/api/sample", sample),
        web.post("/api/options", options),
        web.post("/api/reset", reset),
        web.post("/calls", agent_route),
        web.post("/calls/{cid}/{action:.*}", agent_route),
        web.get("/calls/{cid}/{action:.*}", agent_route),
    ]
)
if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=8000, print=None)
