"""Wire errors shared by the core and the operations router."""

ERRORS = {
    "VERIFICATION_REQUIRED": (403, "Please verify your demo member details first."),
    "VERIFICATION_FAILED": (
        403,
        "Those details did not match. Please try the four digits and birth month again.",
    ),
    "LOCKED": (
        403,
        "I couldn't verify those details after three tries. I've saved a follow-up request.",
    ),
    "INVALID_ZIP": (422, "Please give me a five-digit ZIP code."),
    "NO_MATCH": (
        404,
        "I couldn't find an eligible primary care provider in our demo list for that ZIP.",
    ),
    "NO_SUPPORTED_ANSWER": (
        422,
        "I don't have a supported plan passage for that question. I can request a follow-up.",
    ),
    "COVERAGE_ENDED": (
        403,
        "That visit date is outside your demo coverage. I can't offer an appointment under that coverage.",
    ),
    "UNKNOWN_PROVIDER": (404, "I couldn't find that provider in the demo directory."),
    "NOT_BOOKABLE": (
        409,
        "That provider or time isn't an eligible option for this request. Let me check again.",
    ),
    "VISIT_TYPE_UNAVAILABLE": (
        422,
        "This demo books new-patient primary care visits only. That choice isn't available.",
    ),
    "NO_AVAILABILITY": (
        404,
        "There are no open times for that request in the demo schedule. I can request a follow-up.",
    ),
    "SLOT_IN_PAST": (
        422,
        "That date or time has already passed. Let's choose another.",
    ),
    "TOO_SOON": (
        422,
        "This demo needs at least two hours before a visit. Let's choose a later time.",
    ),
    "OUTSIDE_WINDOW": (
        422,
        "This demo can search only through the next fourteen days. Let's choose a date in that window.",
    ),
    "SLOT_TAKEN": (409, "That time was just taken. Let me check the next opening."),
    "OVERLAP": (
        409,
        "You already have a simulated appointment at that time. Let's choose another.",
    ),
    "NOT_ARMED": (
        409,
        "I need to finish reading the details back, then hear your answer.",
    ),
    "STALE_CONFIRMATION": (
        409,
        "Those details changed or the confirmation expired. I'll read the current choice back.",
    ),
    "NOT_CONFIRMED": (
        409,
        "I haven't booked anything. Please say yes only if you want that exact appointment.",
    ),
    "CALL_ACTIVE": (
        409,
        "The demo can't be reset while a call or booking is in progress.",
    ),
    "CALL_CLOSED": (
        409,
        "This call has ended. Please start a new call to make changes.",
    ),
    "CALL_NOT_FOUND": (404, "I couldn't find this call. Please start a new call."),
    "INVALID_REQUEST": (422, "I couldn't use those details. Please check the request."),
    "IDEMPOTENCY_CONFLICT": (
        409,
        "I couldn't save that turn consistently. Please repeat your answer.",
    ),
    "UNAUTHORIZED": (401, "I'm having trouble connecting to the demo service."),
    "FORBIDDEN": (403, "That action isn't available from this connection."),
    "SERVICE_UNAVAILABLE": (
        503,
        "The demo service is temporarily unavailable. I can't confirm the outcome yet.",
    ),
    "INTERNAL_ERROR": (
        500,
        "Something went wrong with the demo service. I can't confirm the outcome yet.",
    ),
}


class DomainError(Exception):
    def __init__(self, code, speak=None, *, persist=False, **extra):
        self.code = code
        self.status, default_speak = ERRORS[code]
        self.body = {"error": code, "speak": speak or default_speak, **extra}
        # Only explicit state transitions (lock, empty search, invalidation) survive
        # an expected refusal. All other exceptions roll back the transaction.
        self.persist = persist
        super().__init__(code)
