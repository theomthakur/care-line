"""Human attestation ingress. Agents cannot attest patient identity.

The configured policy must describe an independently reviewed process. This
endpoint records its result and evidence reference, never identity documents,
codes, knowledge-based answers, or a model's assertion of identity.
"""

import re
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.routing import APIRoute

from backend.core.common import event, get_call, identifier, utc
from backend.core.errors import DomainError
from backend.core.models import RequestModel
from backend.core.verification import verification_task


class ReviewRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            request.state.reviewer = request.app.state.auth.authenticate(
                request, {"identity_reviewer"}
            )
            return await handler(request)

        return guarded


router = APIRouter(route_class=ReviewRoute)


class Review(RequestModel):
    policy: str
    reference: str
    outcome: Literal["verified", "failed"]
    member_id: str | None = None


@router.post("/identity/calls/{call_id}/review")
def review(call_id: str, body: Review, request: Request):
    reviewer = request.state.reviewer
    db = request.app.state.db
    if not db.identity_policy or body.policy != db.identity_policy:
        raise DomainError("FORBIDDEN")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", body.reference):
        raise DomainError("INVALID_REQUEST")
    if (body.outcome == "verified") != bool(body.member_id):
        raise DomainError("INVALID_REQUEST")
    with db.transaction() as conn:
        call = get_call(conn, call_id)
        previous = conn.execute(
            "SELECT * FROM identity_reviews WHERE call_id=? AND reference=?",
            (call_id, body.reference),
        ).fetchone()
        if previous:
            if previous["outcome"] != body.outcome or (
                body.outcome == "verified" and call["member_id"] != body.member_id
            ):
                raise DomainError("IDEMPOTENCY_CONFLICT")
            return {"status": call["verification_status"]}
        if call["verification_status"] in {"locked", "verified"}:
            raise DomainError("FORBIDDEN")
        now = db.now()
        if body.outcome == "verified":
            if not conn.execute(
                "SELECT 1 FROM members WHERE id=?", (body.member_id,)
            ).fetchone():
                raise DomainError("INVALID_REQUEST")
            conn.execute(
                "UPDATE calls SET verification_status='verified',member_id=? WHERE id=?",
                (body.member_id, call_id),
            )
            event(conn, call_id, "identity_review_verified", now)
        else:
            attempts = call["verification_attempts"] + 1
            conn.execute(
                "UPDATE calls SET verification_attempts=?,verification_status=? WHERE id=?",
                (attempts, "locked" if attempts >= 3 else "unverified", call_id),
            )
            verification_task(conn, call_id, now)
            event(conn, call_id, "identity_review_failed", now)
        conn.execute(
            "INSERT INTO identity_reviews VALUES (?,?,?,?,?,?,?)",
            (
                identifier("review"),
                call_id,
                reviewer.subject,
                body.policy,
                body.reference,
                body.outcome,
                utc(now),
            ),
        )
        return {"status": get_call(conn, call_id)["verification_status"]}
