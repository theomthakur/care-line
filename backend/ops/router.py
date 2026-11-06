# ruff: noqa: B008  (FastAPI Depends in defaults is the framework idiom)
"""Console + handoff routes (contracts/api.md, "Console and handoff interfaces")."""

from __future__ import annotations

import hmac
import os
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from . import admin, summary
from .db import get_conn
from .errors import OpsError
from .state import build_state
from .tasks import CATEGORIES, complete_task, create_task, dedupe_key_for, list_tasks

router = APIRouter()


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


def require_agent_key(x_agent_key: str | None = Header(default=None)) -> None:
    """Agent routes need ``X-Agent-Key``; it is held by the agent, never by browser code."""
    expected = os.getenv("AGENT_KEY", "dev-agent-key")
    if not x_agent_key or not hmac.compare_digest(x_agent_key, expected):
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
