"""Om's agreed HTTP routes. Credentials and tokens stay in adapter code."""

import secrets

from fastapi import APIRouter, Request, Response
from fastapi.routing import APIRoute

from . import availability, booking, calls, models, providers, verification
from .common import get_call
from .errors import DomainError


class AgentRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request: Request):
            expected = request.app.state.agent_key
            supplied = request.headers.get("x-agent-key", "")
            if not expected or not secrets.compare_digest(
                supplied.encode(), expected.encode()
            ):
                raise DomainError("UNAUTHORIZED")
            # Existence and verified identity precede request-body validation,
            # preventing malformed requests from probing unverified state.
            call_id = request.path_params.get("call_id")
            if call_id:
                unverified_route = request.url.path.rsplit("/", 1)[-1] in (
                    "verify",
                    "turn",
                )
                with request.app.state.db.snapshot() as conn:
                    get_call(conn, call_id, verified=not unverified_route, live=False)
            return await handler(request)

        return guarded


router = APIRouter(
    route_class=AgentRoute,
    responses={
        code: {"model": models.ErrorReply}
        for code in (401, 403, 404, 409, 422, 500, 503)
    },
)


@router.post("/calls", response_model=models.CallReply, status_code=201)
def create_call(body: models.CallRequest, request: Request, response: Response):
    result, response.status_code = calls.create_call(request.app.state.db, body.room)
    return result


@router.post("/calls/{call_id}/turn", response_model=models.TurnReply, status_code=201)
def store_turn(
    call_id: str, body: models.TurnRequest, request: Request, response: Response
):
    result, response.status_code = calls.store_turn(
        request.app.state.db, call_id, body.client_turn_id, body.role, body.text
    )
    return result


@router.post("/calls/{call_id}/verify", response_model=models.VerifyReply)
def verify(call_id: str, body: models.VerifyRequest, request: Request):
    return verification.verify_member(
        request.app.state.db, call_id, body.member_digits, body.birth_month
    )


@router.post("/calls/{call_id}/providers", response_model=models.ProvidersReply)
def search_providers(call_id: str, body: models.ProviderRequest, request: Request):
    return providers.search_providers(
        request.app.state.db, call_id, body.specialty, body.zip
    )


@router.post("/calls/{call_id}/select", response_model=models.SelectReply)
def select_provider(call_id: str, body: models.SelectRequest, request: Request):
    return providers.select_provider(request.app.state.db, call_id, body.provider_id)


@router.get("/now", response_model=models.NowReply)
def now(request: Request):
    return availability.get_now(request.app.state.db)


@router.post("/calls/{call_id}/dates", response_model=models.DatesReply)
def dates(call_id: str, body: models.DateRequest, request: Request):
    return availability.resolve_dates(
        request.app.state.db, call_id, body.weekday, body.which
    )


@router.post("/calls/{call_id}/availability", response_model=models.AvailabilityReply)
def find_availability(call_id: str, body: models.AvailabilityRequest, request: Request):
    return availability.availability(
        request.app.state.db, call_id, body.date_from, body.date_to, body.part_of_day
    )


@router.post("/calls/{call_id}/slot", response_model=models.SlotReply)
def choose_slot(call_id: str, body: models.SlotRequest, request: Request):
    return booking.select_slot(request.app.state.db, call_id, body.slot_id)


@router.post("/calls/{call_id}/appointment/preview", response_model=models.PreviewReply)
def preview(call_id: str, body: models.EmptyRequest, request: Request):
    return booking.preview_booking(request.app.state.db, call_id)


@router.post("/calls/{call_id}/appointment/armed", response_model=models.ArmedReply)
def arm(call_id: str, body: models.TokenRequest, request: Request):
    return booking.arm_booking(request.app.state.db, call_id, body.token)


@router.post(
    "/calls/{call_id}/appointment/confirm",
    response_model=models.ConfirmReply,
    status_code=201,
)
def confirm(
    call_id: str, body: models.TokenRequest, request: Request, response: Response
):
    result, response.status_code = booking.confirm_booking(
        request.app.state.db, call_id, body.token
    )
    return result


@router.get("/calls/{call_id}/appointment", response_model=models.AppointmentsReply)
def appointments(call_id: str, request: Request):
    return booking.get_appointments(request.app.state.db, call_id)
