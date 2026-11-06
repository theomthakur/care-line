"""Strict request schemas and documented caller-facing responses."""

import re
from datetime import date
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ID = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EmptyRequest(RequestModel):
    pass


class CallRequest(RequestModel):
    room: ID


class TurnRequest(RequestModel):
    client_turn_id: ID
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def finalized_text(cls, value):
        if not value.strip():
            raise ValueError("empty text")
        return value


class VerifyRequest(RequestModel):
    member_digits: ID
    birth_month: int = Field(ge=1, le=12)


class ProviderRequest(RequestModel):
    specialty: ID
    zip: str


class SelectRequest(RequestModel):
    provider_id: ID


class DateRequest(RequestModel):
    weekday: Literal[
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "today",
        "tomorrow",
    ]
    which: Literal["this", "next", "unspecified"]


class AvailabilityRequest(RequestModel):
    date_from: str
    date_to: str
    part_of_day: Literal["any", "morning", "afternoon"]

    @field_validator("date_from", "date_to")
    @classmethod
    def calendar_date(cls, value):
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("Expected YYYY-MM-DD")
        date.fromisoformat(value)
        return value


class SlotRequest(RequestModel):
    slot_id: ID


class TokenRequest(RequestModel):
    token: ID


class Reply(BaseModel):
    speak: str


class Member(BaseModel):
    name: str
    id_masked: str
    plan: str
    network: str
    active: bool


class Provider(BaseModel):
    id: str
    name: str
    specialty: Literal["primary care"]
    zip: str
    phone: str
    accepting_new_patients: bool


class Excluded(BaseModel):
    id: str
    name: str
    reason_code: Literal["NOT_BOOKABLE", "VISIT_TYPE_UNAVAILABLE"]
    reason: str


class Evidence(BaseModel):
    id: str
    title: str
    text: str


class Slot(BaseModel):
    slot_id: str
    provider_id: str
    starts_at: str
    ends_at: str
    timezone: Literal["America/New_York"]
    text: str


class Appointment(BaseModel):
    appointment_id: str
    status: Literal["booked"]
    confirmation: str
    provider_id: str
    slot_id: str
    doctor: str
    phone: str
    starts_at: str
    ends_at: str
    timezone: Literal["America/New_York"]
    when: str
    simulated: Literal[True]


class CallReply(Reply):
    call_id: str
    status: Literal["live"]
    created_at: str


class TurnReply(Reply):
    turn_seq: int
    received_at: str


class VerifyReply(Reply):
    status: Literal["verified"]
    member: Member


class ProvidersReply(Reply):
    providers: list[Provider]
    excluded: list[Excluded]
    evidence: list[Evidence]
    request_version: int


class SelectReply(Reply):
    provider: Provider
    evidence: Evidence
    evidence_id: str
    request_version: int


class NowReply(Reply):
    now: str
    business_date: str
    business_time: str
    timezone: Literal["America/New_York"]


class Candidate(BaseModel):
    date: str
    text: str


class DatesReply(Reply):
    candidates: list[Candidate]
    needs_clarification: bool


class AvailabilityReply(Reply):
    slots: list[Slot]
    request_version: int


class SlotReply(Reply):
    slot: Slot
    revision: int
    status: Literal["slot"]


class PreviewReply(Reply):
    token: str
    revision: int
    status: Literal["preview"]
    read_back: str


class ArmedReply(Reply):
    status: Literal["armed"]
    armed_seq: int
    armed_at: str
    expires_at: str


class ConfirmReply(Reply):
    appointment: Appointment


class AppointmentsReply(Reply):
    appointments: list[Appointment]


class ErrorReply(Reply):
    error: str
    attempts_remaining: Optional[int] = None
    task_id: Optional[str] = None
