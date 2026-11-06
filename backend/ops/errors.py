"""Error envelope from contracts/errors.md: ``{"error": CODE, "speak": sentence}``."""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse

CATALOG: dict[str, tuple[int, str]] = {
    "UNAUTHORIZED": (401, "I'm having trouble connecting to the demo service."),
    "CALL_ACTIVE": (
        409,
        "The demo can't be reset while a call or booking is in progress.",
    ),
    "CALL_CLOSED": (
        409,
        "This call has ended. Please start a new call to make changes.",
    ),
    "CALL_NOT_FOUND": (404, "I couldn't find this call. Please start a new call."),
    "TASK_NOT_FOUND": (404, "That follow-up request could not be found."),
    "SLOT_NOT_FOUND": (404, "That time could not be found in the demo schedule."),
    "SLOT_TAKEN": (409, "That time was just taken. Let me check the next opening."),
    "INVALID_REQUEST": (422, "I couldn't use those details. Please check the request."),
    "SERVICE_UNAVAILABLE": (
        503,
        "The demo service is temporarily unavailable. I can't confirm the outcome yet.",
    ),
    "INTERNAL_ERROR": (
        500,
        "Something went wrong with the demo service. I can't confirm the outcome yet.",
    ),
}


class OpsError(HTTPException):
    def __init__(self, code: str):
        status, speak = CATALOG[code]
        super().__init__(status_code=status, detail={"error": code, "speak": speak})


def envelope(exc: HTTPException) -> JSONResponse:
    """Render any HTTPException in the contract envelope (no framework arrays or traces)."""
    d = exc.detail
    if isinstance(d, dict) and "error" in d and "speak" in d:
        return JSONResponse(d, status_code=exc.status_code)
    code = "INVALID_REQUEST" if exc.status_code < 500 else "INTERNAL_ERROR"
    return JSONResponse(
        {"error": code, "speak": CATALOG[code][1]}, status_code=exc.status_code
    )
