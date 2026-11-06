# MemberGuide errors — proposed contract

Every non-2xx response is JSON with required `error: string` and `speak: string`.
Do not return framework validation arrays, stack traces, member records or tokens.
Only verification errors add the optional fields `attempts_remaining: integer`
and `task_id: string` (only when a task was created). No field-specific identity
failure details. All example healthcare data is synthetic.

```json
{"error":"SLOT_TAKEN","speak":"That time was just taken. Let me check the next opening."}
```

HTTP status conveys the broad class; clients branch on `error`, never on spoken
wording. Domain failures are non-2xx, including empty search/availability. The
success schemas do not acquire an `error` field. Before any data access, check
agent/operator access, then call existence, then verification, then domain rules.
This prevents an unverified call probing provider or booking state.

| Code | HTTP | Meaning / expected `speak` | Recovery |
| --- | --- | --- | --- |
| `VERIFICATION_REQUIRED` | 403 | “Please verify your demo member details first.” | Run verification; no member data returned. |
| `VERIFICATION_FAILED` | 403 | “Those details did not match. Please try the four digits and birth month again.” | Same sentence for either field; `attempts_remaining` is 2, then 1. After two failures ask digits individually. |
| `LOCKED` | 403 | “I couldn't verify those details after three tries. I've saved a follow-up request.” | `attempts_remaining: 0`, `task_id`; create exactly one verification-failure task, no more attempts in this call. |
| `INVALID_ZIP` | 422 | “Please give me a five-digit ZIP code.” | Clarify ZIP; malformed input leaves current draft unchanged. |
| `NO_MATCH` | 404 | “I couldn't find an eligible primary care provider in our demo list for that ZIP.” | Confirm ZIP or offer follow-up; old search/selection is cleared. |
| `NO_SUPPORTED_ANSWER` | 422 | “I don't have a supported plan passage for that question. I can request a follow-up.” | No invented coverage; `knowledge_gap` task if requested. |
| `COVERAGE_ENDED` | 403 | “Your demo coverage ended on October 31, 2026. I can't offer an appointment under that coverage.” | Sentence uses this verified member's stored end date; no booking. Future date beyond coverage also uses this code. |
| `UNKNOWN_PROVIDER` | 404 | “I couldn't find that provider in the demo directory.” | Search again. |
| `NOT_BOOKABLE` | 409 | “That provider or time isn't an eligible option for this request. Let me check again.” | Missing selection, guessed/out-of-network provider, wrong provider slot, or slot outside latest offer set; do not bypass by ID. |
| `VISIT_TYPE_UNAVAILABLE` | 422 | “This demo books new-patient primary care visits only. That choice isn't available.” | For an existing-patient-only provider, use “That office isn't accepting new patients.” Offer eligible alternatives/follow-up. |
| `NO_AVAILABILITY` | 404 | “There are no open times for that request in the demo schedule. I can request a follow-up.” | Replace offers with empty list; widen dates within window or `waitlist` task. |
| `SLOT_IN_PAST` | 422 | “That date or time has already passed. Let's choose another.” | Get backend dates and availability again. |
| `TOO_SOON` | 422 | “This demo needs at least two hours before a visit. Let's choose a later time.” | Slot start must be at least now + two hours; exactly two hours is allowed. |
| `OUTSIDE_WINDOW` | 422 | “This demo can search only through the next fourteen days. Let's choose a date in that window.” | Use backend business date; no model date arithmetic. |
| `SLOT_TAKEN` | 409 | “That time was just taken. Let me check the next opening.” | Invalidate preview; refresh availability, choose, preview, read back, arm, obtain a new yes. Provider interval conflict also uses this code. |
| `OVERLAP` | 409 | “You already have a simulated appointment at that time. Let's choose another.” | Member overlap across all calls; no conflicting appointment details disclosed. Fresh preview for a different slot. |
| `NOT_ARMED` | 409 | “I need to finish reading the details back, then hear your answer.” | No uninterrupted read-back or no later user turn; never book on an early yes. Replay the read-back via a fresh preview if needed. |
| `STALE_CONFIRMATION` | 409 | “Those details changed or the confirmation expired. I'll read the current choice back.” | Invalid, foreign, expired or superseded token/hash. Invalid tokens use one response; no other-call data. New preview, full read-back and later yes. |
| `NOT_CONFIRMED` | 409 | “I haven't booked anything. Please say yes only if you want that exact appointment.” | Latest user turn is no, qualified yes, unclear or a correction. Apply corrections before a new preview. No automatic confirm retry. |
| `CALL_ACTIVE` | 409 | “The demo can't be reset while a call or booking is in progress.” | Finish call and pending writes before reset. |
| `CALL_CLOSED` | 409 | “This call has ended. Please start a new call to make changes.” | New call; committed confirm replays/read reconciliation remain allowed. |
| `CALL_NOT_FOUND` | 404 | “I couldn't find this call. Please start a new call.” | Adapter lifecycle error; never fall back to latest call for a tool request. |
| `TASK_NOT_FOUND` | 404 | “That follow-up request could not be found.” | Refresh console task list. |
| `SLOT_NOT_FOUND` | 404 | “That time could not be found in the demo schedule.” | Unknown ID on the admin route; member slot route uses NOT_BOOKABLE if not offered. |
| `INVALID_REQUEST` | 422 | “I couldn't use those details. Please check the request.” | Invalid types, missing/unknown fields, empty text, malformed dates/JSON or reversed range. Do not retry unchanged. |
| `IDEMPOTENCY_CONFLICT` | 409 | “I couldn't save that turn consistently. Please repeat your answer.” | Same client_turn_id with different role/text. Stop tools; reconcile original delivery before accepting another answer. |
| `UNAUTHORIZED` | 401 | “I'm having trouble connecting to the demo service.” | Missing/invalid agent key; configuration fix, no member data. |
| `FORBIDDEN` | 403 | “That action isn't available from this connection.” | Operator origin/access denied; no write. |
| `SERVICE_UNAVAILABLE` | 503 | “The demo service is temporarily unavailable. I can't confirm the outcome yet.” | Database busy/unavailable. Reconcile any possible write before retrying with the same token. |
| `INTERNAL_ERROR` | 500 | “Something went wrong with the demo service. I can't confirm the outcome yet.” | Log server-side; reconcile possible booking, offer tool-failure follow-up when service works. |

Domain codes through `CALL_ACTIVE` come from plan section 8. Transport/lifecycle/retry
codes after `CALL_ACTIVE` make failure behavior explicit; they need team agreement
with the rest of this draft. `REFERRAL_REQUIRED` is reserved for a future
specialist extension, not emitted by this primary-care-only contract.

Example first verification failure:

```json
{"error":"VERIFICATION_FAILED","speak":"Those details did not match. Please try the four digits and birth month again.","attempts_remaining":2}
```

Example lock (the task ID is an internal reference, not a spoken confirmation):

```json
{"error":"LOCKED","speak":"I couldn't verify those details after three tries. I've saved a follow-up request.","attempts_remaining":0,"task_id":"task_verify_c_02"}
```

For confirmation, a committed-token replay wins over expiry/closed-call checks.
For an uncommitted token: stale/foreign/hash-invalid → `STALE_CONFIRMATION`;
not armed or no post-arm user turn → `NOT_ARMED`; later turn not an allowed yes
→ `NOT_CONFIRMED`. Then apply the transactional eligibility and schedule checks.
All guards in [api.md](api.md) still apply; this ordering does not replace them.

Connection loss and client timeouts have **no HTTP status or server error body**.
Om's adapter should say “I couldn't confirm whether that was saved. Let me check.”
and reconcile through `GET /calls/{id}/appointment` or repeat confirm with the
same token. Never convert a missing response to a fake SLOT_TAKEN or success.
Siddhant shows a backend connection error, retains the call ID, and never infers
success from a local click or draft. `summary.outcome: "unknown"` has null
confirmation until committed state is available.

Domain refusals such as NO_MATCH or NOT_CONFIRMED are expected outcomes, not
infrastructure failures. Automatic tool-failure escalation counts transport,
timeout and 5xx failures; unsupported answers count toward the separate
unanswered-question policy. See the pending ops-signals agreement in api.md.
