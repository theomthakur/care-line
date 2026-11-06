"""Call and ordered finalized-turn ingress shared with the voice adapter."""

from .common import event, get_call, identifier, utc
from .errors import DomainError


def create_call(db, room):
    from backend.security import access_context, authorize_call, digest

    access = access_context.get()
    if access is not None and len(access.call_key) < 32:
        raise DomainError("FORBIDDEN")
    with db.transaction() as conn:
        call = conn.execute("SELECT * FROM calls WHERE room=?", (room,)).fetchone()
        status = 200
        if call is None:
            now = db.now()
            call_id = identifier("call")
            conn.execute(
                "INSERT INTO calls(id,room,created_at) VALUES (?,?,?)",
                (call_id, room, utc(now)),
            )
            if access is not None:
                conn.execute(
                    "INSERT INTO call_access VALUES (?,?,?)",
                    (call_id, access.principal.subject, digest(access.call_key)),
                )
            event(conn, call_id, "call_created", now)
            call = get_call(conn, call_id)
            status = 201
        elif access is not None:
            authorize_call(conn, call["id"], access)
        return {
            "call_id": call["id"],
            # Return the original creation receipt on room-key replay, including
            # when the call has since ended. It never reopens that call.
            "status": "live",
            "created_at": call["created_at"],
            "speak": "",
        }, status


def store_turn(db, call_id, client_turn_id, role, text):
    with db.transaction() as conn:
        call = get_call(conn, call_id, live=False)
        if db.environment == "production" and call["verification_status"] != "verified":
            text = "[identity pending]"
        previous = conn.execute(
            "SELECT * FROM turns WHERE call_id=? AND client_turn_id=?",
            (call_id, client_turn_id),
        ).fetchone()
        if previous:
            if previous["role"] != role or previous["text"] != text:
                raise DomainError("IDEMPOTENCY_CONFLICT")
            return {
                "turn_seq": previous["seq"],
                "received_at": previous["received_at"],
                "speak": "",
            }, 200
        if call["status"] != "live" and role != "assistant":
            raise DomainError("CALL_CLOSED")
        seq = conn.execute(
            "SELECT COALESCE(MAX(seq),0)+1 FROM turns WHERE call_id=?", (call_id,)
        ).fetchone()[0]
        received_at = utc(db.now())
        conn.execute(
            "INSERT INTO turns VALUES (?,?,?,?,?,?)",
            (call_id, seq, client_turn_id, role, text, received_at),
        )
        return {"turn_seq": seq, "received_at": received_at, "speak": ""}, 201
