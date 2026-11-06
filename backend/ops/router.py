# ruff: noqa: B008  (FastAPI Depends in defaults is the framework idiom)
"""Console + handoff routes (contracts/api.md, "Console and handoff interfaces")."""

from __future__ import annotations

import hmac
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from . import admin, summary
from .calls import DEFAULT_RECENT, MAX_RECENT, list_calls
from .db import get_conn
from .errors import OpsError
from .state import build_state
from .tasks import CATEGORIES, complete_task, create_task, dedupe_key_for, list_tasks


class OpsRoute(APIRoute):
    """Render OpsError in the contract envelope here, so it survives a host app whose own
    HTTPException handler would flatten it (core's ``create_app`` maps those to INVALID_REQUEST)."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            try:
                return await handler(request)
            except OpsError as exc:
                return JSONResponse(exc.detail, status_code=exc.status_code)

        return guarded


router = APIRouter(route_class=OpsRoute)


def install(app: FastAPI) -> None:
    """Mount the router and render every error in the contract envelope."""
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from .errors import CATALOG, envelope

    app.include_router(router)
    app.add_exception_handler(StarletteHTTPException, lambda _r, e: envelope(e))
    app.add_exception_handler(
        RequestValidationError,
        lambda _r, _e: JSONResponse(
            {"error": "INVALID_REQUEST", "speak": CATALOG["INVALID_REQUEST"][1]},
            status_code=422,
        ),
    )


def require_agent_key(
    request: Request, x_agent_key: str | None = Header(default=None)
) -> None:
    """The host's explicit agent key is authoritative; absent configuration fails closed."""
    expected = getattr(request.app.state, "agent_key", "")
    if (
        not expected
        or not x_agent_key
        or not hmac.compare_digest(x_agent_key, expected)
    ):
        raise OpsError("UNAUTHORIZED")


async def _body(request: Request, allowed: set[str]) -> dict[str, Any]:
    """Strict JSON object: unknown fields are refused (e.g. member_id, confirmed, yes)."""
    try:
        raw = await request.body()
        data = {} if not raw else await request.json()
    except ValueError:
        raise OpsError("INVALID_REQUEST") from None
    if not isinstance(data, dict) or set(data) - allowed:
        raise OpsError("INVALID_REQUEST")
    return data


# ---------------------------------------------------------------- console routes


@router.get("/calls/latest")
def calls_latest(conn: sqlite3.Connection = Depends(get_conn)):
    return {"state": build_state(conn), "speak": ""}


@router.get("/providers/directory")
def providers_directory(conn: sqlite3.Connection = Depends(get_conn)):
    """Read-only provider directory with open times per day, for the operator workspace."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from . import clock

    eastern = ZoneInfo("America/New_York")
    now = clock.now().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for p in conn.execute("SELECT * FROM providers ORDER BY CAST(SUBSTR(id,2) AS INT)"):
        networks = [
            r["network"]
            for r in conn.execute(
                "SELECT network FROM provider_networks WHERE provider_id=? ORDER BY network",
                (p["id"],),
            )
        ]
        days: dict[str, dict[str, int]] = {}
        next_open: list[str] = []
        for r in conn.execute(
            "SELECT starts_at,state FROM slots WHERE provider_id=? AND starts_at>? ORDER BY starts_at",
            (p["id"], now),
        ):
            local = datetime.fromisoformat(
                r["starts_at"].replace("Z", "+00:00")
            ).astimezone(eastern)
            day = days.setdefault(local.date().isoformat(), {"open": 0, "total": 0})
            day["total"] += 1
            if r["state"] == "open":
                day["open"] += 1
                if len(next_open) < 3:
                    next_open.append(r["starts_at"])
        out.append(
            {
                "id": p["id"],
                "name": p["name"],
                "specialty": p["specialty"],
                "zip": p["zip"],
                "phone": p["phone"],
                "accepting_new_patients": bool(p["accepting_new_patients"]),
                "networks": networks,
                "open_slots": sum(d["open"] for d in days.values()),
                "next_open": next_open,
                "days": [{"date": k, **v} for k, v in sorted(days.items())],
            }
        )
    return {"providers": out, "speak": ""}


@router.get("/calls/history")
def calls_history(conn: sqlite3.Connection = Depends(get_conn)):
    """Recent demo calls, with no credentials or transcript contents in the list."""
    rows = conn.execute(
        "SELECT c.id,c.status,c.created_at,m.display_name,c.verification_status,"
        "EXISTS(SELECT 1 FROM appointments a WHERE a.call_id=c.id AND a.status='booked') AS booked "
        "FROM calls c LEFT JOIN members m ON m.id=c.member_id "
        "ORDER BY c.created_at DESC,c.id DESC LIMIT 100"
    ).fetchall()
    return {
        "calls": [
            {
                "call_id": r["id"],
                "status": r["status"],
                "created_at": r["created_at"],
                "member": r["display_name"]
                if r["verification_status"] == "verified"
                else None,
                "booked": bool(r["booked"]),
            }
            for r in rows
        ]
    }


@router.get("/calls")
def calls_list(
    recent: int = Query(DEFAULT_RECENT, ge=0, le=MAX_RECENT),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """All live calls plus the most recent finished ones, for the console's call list."""
    return {"calls": list_calls(conn, recent), "speak": ""}


@router.get("/calls/{call_id}/state")
def call_state(call_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    """Full console state for one call. An unknown id is an error, never "the latest"."""
    state = build_state(conn, call_id)
    if state is None:
        raise OpsError("CALL_NOT_FOUND")
    return {"state": state, "speak": ""}


@router.get("/tasks")
def tasks(status: str | None = None, conn: sqlite3.Connection = Depends(get_conn)):
    return {"tasks": list_tasks(conn, status), "speak": ""}


@router.post("/tasks/{task_id}/complete")
async def tasks_complete(
    task_id: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    await _body(request, set())
    return {"task": complete_task(conn, task_id), "speak": ""}


@router.post("/admin/take-slot")
async def admin_take_slot(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    data = await _body(request, {"slot_id"})
    slot_id = data.get("slot_id")
    if not isinstance(slot_id, str) or not slot_id:
        raise OpsError("INVALID_REQUEST")
    return admin.take_slot(conn, slot_id)


@router.post("/admin/reset")
async def admin_reset(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    await _body(request, set())
    return admin.reset_demo(conn)


# ---------------------------------------------------------------- agent routes (ops-owned)


def _call(conn: sqlite3.Connection, call_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, status FROM calls WHERE id = ?", (call_id,)
    ).fetchone()
    if row is None:
        raise OpsError("CALL_NOT_FOUND")
    return row


@router.post("/calls/{call_id}/followup", dependencies=[Depends(require_agent_key)])
async def calls_followup(
    call_id: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    data = await _body(request, {"category", "detail"})
    category, detail = data.get("category"), data.get("detail")
    if (
        category not in CATEGORIES
        or not isinstance(detail, str)
        or not detail.strip()
        or len(detail) > 1000
    ):
        raise OpsError("INVALID_REQUEST")
    if _call(conn, call_id)["status"] == "finalized":
        raise OpsError("CALL_CLOSED")
    task, created = create_task(
        conn, call_id, category, detail.strip(), dedupe_key_for(category, detail)
    )
    ref = task["packet"]["reference"]
    spoken_ref = " ".join(ref.replace("-", " "))
    speak = f"I saved follow-up request {spoken_ref}. No appointment has been booked."
    return JSONResponse(
        {"task": task, "speak": speak}, status_code=201 if created else 200
    )


@router.post("/calls/{call_id}/finalize", dependencies=[Depends(require_agent_key)])
async def calls_finalize(
    call_id: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
):
    await _body(request, set())
    _call(conn, call_id)
    return {"summary": summary.finalize_call(conn, call_id), "speak": ""}
