# MemberGuide shared API — proposed contract

Shared API design notes for the voice agent, booking service and workspace.
The running implementation and tests are the source of truth for behavior. All people, plans, schedules and bookings here are synthetic.

First build: one verified member per call, primary care, new patients, in-person
visits of exactly 30 minutes, against a simulated schedule. Specialists,
referrals, returning patients, telehealth, holds, cancellation and rescheduling
are stretch and have no routes in this contract.

The [care-journeys data extension](care-journeys.md) adds schema v2, synthetic
specialist/referral/history fixtures and Pydantic extension models. It documents
the remaining backend, Om and Sid integration work. Its proposed new routes are
not mounted; this document continues to describe the live primary-care API.

## Transport, access and common types

- Base URL: `http://127.0.0.1:8000`, with the plan's unversioned paths.
- JSON requests and responses; POST requests use `Content-Type: application/json`.
- Agent routes require `X-Agent-Key`, held only in agent/server configuration.
  A call ID identifies state; it is not a credential. The model never chooses
  the call ID, member ID, token, turn sequence or a consent flag.
- Console routes are `GET /calls/latest`, `GET /tasks`, `POST /tasks/{id}/complete`,
  and `/admin/*`. Proposed access: local operator only, served through the local
  dashboard origin/dev proxy. No agent key in browser code. Bind to loopback,
  restrict allowed origins, and reject cross-origin operator writes. Remote
  dashboard hosting requires a separate access agreement.
- All success bodies are flat JSON objects with `speak: string`. Internal and
  console routes use `speak: ""`; only caller-facing lines should be spoken.
  Errors use [errors.md](errors.md), including validation and unexpected errors.
- Field names are `snake_case`. In the schemas below fields are required unless
  marked `?`; `T | null` is a required nullable field. Reject unknown request
  fields, including `member_id`, `confirmed` and `yes`. Responses may gain
  additive fields; clients should ignore unknown response fields.
- `ID` is a nonempty opaque string. Examples use readable IDs, but clients never
  parse them. Tokens stay in Om's adapter and never go to TTS or dashboard state.
- `UTC` is an RFC 3339 string, canonical storage `YYYY-MM-DDTHH:MM:SSZ`.
  `Date` is a valid `YYYY-MM-DD`. `ZIP` is a five-digit string, preserving zeros.
  `month` is an integer 1–12; booleans are JSON booleans.
- The backend is the only clock. Local dates, coverage dates and spoken times
  use `America/New_York`, including daylight saving changes. All intervals are
  half-open `[starts_at, ends_at)`, so adjacent appointments do not overlap.
- POSTs with no input accept `{}`. Ordinary successes are 200; creation and
  replay exceptions are specified below. No pagination, streaming or SSE.

Reusable response schemas (these are structural notation, not JSON payloads):

| Type | Fields |
| --- | --- |
| `Member` | `name: string` (display name, e.g. Maya T.), `id_masked: string`, `plan: string`, `network: string`, `active: boolean` (as of backend business date) |
| `Provider` | `id: ID`, `name: string`, `specialty: "primary care"`, `zip: ZIP`, `phone: string`, `accepting_new_patients: boolean` |
| `Excluded` | `id: ID`, `name: string`, `reason_code: "NOT_BOOKABLE" | "VISIT_TYPE_UNAVAILABLE"`, `reason: string` |
| `Evidence` | `id: ID`, `title: string`, `text: string` (verbatim synthetic plan passage) |
| `Slot` | `slot_id: ID`, `provider_id: ID`, `starts_at: UTC`, `ends_at: UTC`, `timezone: "America/New_York"`, `text: string` (weekday, month, day, year, AM/PM, Eastern time) |
| `Appointment` | `appointment_id: ID`, `status: "booked"`, `confirmation: string`, `provider_id: ID`, `slot_id: ID`, `doctor: string`, `phone: string`, `starts_at: UTC`, `ends_at: UTC`, `timezone: "America/New_York"`, `when: string`, `simulated: true` |
| `Turn` | `seq: integer >= 1`, `role: "user" | "assistant"`, `text: string`, `received_at: UTC`, `t: number >= 0` (seconds since call creation, from backend receipt time) |
| `Summary` | `outcome: "booked" | "followup" | "not_completed" | "unknown"`, `reason: string`, `text: string`, `confirmation: string | null` |

`Member.active` does not establish coverage on a future visit: recheck the
appointment's Eastern date against the member's inclusive coverage dates.
No raw member record, birth month, verification digits, token or detail hash is
returned to the dashboard. Mask verification answers in the transcript projection
before returning console state; retain original finalized turns server-side for
consent checks. The separate printed synthetic demo card is not verified state.

## Voice tool mapping

| Model-facing tool | Adapter's routes |
| --- | --- |
| `verify_demo_member` | `/verify` |
| `find_network_providers` | `/providers`, then `/select` after the caller chooses |
| `find_slots` | `/dates`, `/availability` |
| `prepare_appointment` | `/slot`, `/appointment/preview`, code-spoken read-back, `/appointment/armed` |
| `confirm_appointment` | `/appointment/confirm`; `/appointment` to reconcile an uncertain result |
| `create_followup` | `/followup` |

All paths in this table are relative to `/calls/{id}`. Call creation, `/now`,
ordered `/turn`, finalize and dashboard routes are adapter/operator operations,
not extra model-facing tools. Return only the useful caller facts and `speak`
from the adapter to the model; keep transport IDs and tokens in code.

## Call and verification

### POST /calls — agent

Request: `{room: string}` (nonempty LiveKit room identifier).
Response: `{call_id: ID, status: "live", created_at: UTC, speak: ""}`.
201 for creation, 200 for a retry with the same room and same call. Room is the
creation idempotency key; a new real call uses a new room. Initial state is
unverified, with no member data. [Example](examples/call-created.json).

### POST /calls/{id}/turn — agent

Request: `{client_turn_id: ID, role: "user" | "assistant", text: string}`.
`text` must be nonempty finalized text, never partial STT. Response:
`{turn_seq: integer >= 1, received_at: UTC, speak: ""}`. 201 on insert, 200 on
identical retry. Backend assigns strictly increasing per-call sequences, shared
by both roles. Same client ID with different role/text is `IDEMPOTENCY_CONFLICT`.

Om must await each user-turn write in conversation order before any tool or
safety action, and block tools if storage fails. No background user writes.
Assistant turns may be forwarded in the background. Use the same client ID when
retrying a delivery; an old retry must not become the newest user turn. For the
plan's older `/transcript` reference, use `/turn` for both roles; no duplicate
transcript route is needed. [Example](examples/turn-stored.json).

### POST /calls/{id}/verify — agent

Request example:

```json
{"member_digits":"4417","birth_month":4}
```

`member_digits: string` is four digits or spoken digit words. Normalize spaces,
hyphens and English zero–nine (including “oh” as zero); uncertain STT such as
“for” must be clarified, never guessed. Three failed matches lock this call and
create one `verification_failed` task. A syntactically valid failed attempt
counts; invalid JSON/types do not. First two failures: `VERIFICATION_FAILED`;
third and later: `LOCKED`. Errors never identify the failed field.

Success: `{status: "verified", member: Member, speak: string}`.
[Example](examples/verified.json). Verification binds the member to the call;
reverification cannot switch identity. An already verified call returns its
existing verified result. Ended coverage still permits identity verification
with `member.active: false`; search and booking return `COVERAGE_ENDED`.

All subsequent member routes resolve identity from this call. Without that
binding they return `VERIFICATION_REQUIRED`. Follow-up, turns and finalization
also work for unverified or locked callers, without revealing member data.

## Provider search and selection

### POST /calls/{id}/providers — agent, verified

Request: `{specialty: "primary care", zip: ZIP}`. Example:

```json
{"specialty":"primary care","zip":"10023"}
```

Response: `{providers: Provider[], excluded: Excluded[], evidence: Evidence[],
request_version: integer >= 1, speak: string}`.
[Example](examples/providers.json). At most three eligible providers. Filter
network membership and acceptance of new patients before ranking; excluded
providers are separately recorded with reasons, never selectable options.
Return the preventive passage for the member's plan, without a cost guarantee.

Use section 9's ZIP ordering: 10019 → 10023 → 10024; 10023 → 10024 → 10019;
10024 → 10023 → 10019. Ties use provider ID. Say “nearest in our list,” not a
distance. Malformed ZIP is `INVALID_ZIP`; any other well-formed ZIP or an empty
eligible list is `NO_MATCH`. Unsupported specialty is `VISIT_TYPE_UNAVAILABLE`.
Missing preventive passage is `NO_SUPPORTED_ANSWER`; do not invent one.

A valid new search increments `request.version`, replaces results and exclusions,
and clears selection, offered slots, draft and arming even if it finds no match.
Malformed requests leave state unchanged. Check current coverage first.

### POST /calls/{id}/select — agent, verified

Request: `{provider_id: ID}`. Must be in the latest eligible results. Response:
`{provider: Provider, evidence: Evidence, evidence_id: ID, request_version: integer,
speak: string}`. [Example](examples/provider-selected.json).
Code selects `GOLD-PREV` or `BASIC-PREV`; this passage is evidence, not medical
advice or a promise that every service is covered. Unknown ID is
`UNKNOWN_PROVIDER`; out of network or outside current results is `NOT_BOOKABLE`;
not accepting new patients is `VISIT_TYPE_UNAVAILABLE`.
Each successful selection increments request version, clears slots and preview.

## Dates and appointment availability

### GET /now — agent

Response: `{now: UTC, business_date: Date, business_time: string,
timezone: "America/New_York", speak: ""}`.
[Example](examples/now.json). `business_time` includes its numeric UTC offset.

### POST /calls/{id}/dates — agent, verified

Request: `{weekday: "monday" | "tuesday" | "wednesday" | "thursday" | "friday" |
"saturday" | "sunday" | "today" | "tomorrow", which: "this" | "next" | "unspecified"}`.
`today` and `tomorrow` require `which: "unspecified"`. Response:
`{candidates: [{date: Date, text: string}], needs_clarification: boolean, speak: string}`.
[Example](examples/dates.json).

Code resolves relative dates using `/now`. `today`/`tomorrow` give one candidate.
For a weekday, `this` is the earliest occurrence on or after the business date;
`next` or `unspecified` returns that occurrence and the one seven days later,
within the 14-day date window, asking which when two remain. No silent inference
from “next Friday.” These are calendar dates, not promises of availability;
weekends may be returned but contain no slots. No candidate: `OUTSIDE_WINDOW`.

### POST /calls/{id}/availability — agent, verified, provider selected

Request: `{date_from: Date, date_to: Date, part_of_day: "any" | "morning" | "afternoon"}`.
Dates are inclusive Eastern calendar dates. Morning is before noon, afternoon
is noon onward. Example:

```json
{"date_from":"2026-11-13","date_to":"2026-11-13","part_of_day":"afternoon"}
```

Response: `{slots: Slot[], request_version: integer, speak: string}`.
[Example](examples/availability.json). Return at most two open, in-person slots,
ordered by start time then slot ID. Slot start must be at least two hours after
the backend's current instant, and its Eastern date no later than business date
+ 14 calendar days. A past date gives `SLOT_IN_PAST`; over-window dates give
`OUTSIDE_WINDOW`; reversed dates give `INVALID_REQUEST`. For today, filter past
and too-soon slots; if none remain return `NO_AVAILABILITY`. Coverage must be
valid for each returned visit date. A range entirely after coverage ends gives
`COVERAGE_ENDED`; partially covered ranges return only covered slots.

Each valid query increments request version, replaces the latest offer set and clears chosen slot, preview
and arming, including on `NO_AVAILABILITY`. No provider gives `NOT_BOOKABLE`.
The backend retains both this offer set and the query in call state. An offer is
never a reservation. Seeded office hours are weekdays 9 AM–5 PM Eastern; each
slot starts on a 00/30 minute boundary and ends 30 minutes later.

### POST /calls/{id}/slot — agent, verified

Request: `{slot_id: ID}`. Response:
`{slot: Slot, revision: integer >= 1, status: "slot", speak: string}`.
[Example](examples/slot-selected.json). Must belong to the selected provider and
latest offer set. Otherwise `NOT_BOOKABLE`; a previously offered but now taken
slot is `SLOT_TAKEN`. Recheck time/coverage and new-patient eligibility.
Each successful choice creates the next draft revision and invalidates any
previous preview/arming. The revision is for display, never write authority.

## Booking preview, arming and confirmation

### POST /calls/{id}/appointment/preview — agent, verified

Request: `{}`. Response: `{token: ID, revision: integer, status: "preview",
read_back: string, speak: ""}`. [Example](examples/booking-preview.json).
Requires a valid selected slot. Rechecks eligibility and time. Stores the
canonical detail hash, member, provider, slot, visit type, start/end instants and
latest user-turn sequence. It books nothing and holds nothing. Each preview
issues a new token and invalidates any earlier uncommitted token. Hash never
comes from the request. `read_back` states member, doctor, weekday/date/year,
time, new-patient/in-person visit, simulated schedule and asks permission.

Example arming and confirmation request bodies both use the adapter-held token:

```json
{"token":"demo_preview_c01_r1"}
```

Om speaks exactly `read_back` in code, waits for that speech to finish, checks
interruption, then calls armed. A model-generated paraphrase cannot arm booking.
The integration must observe the actual read-back speech handle's playout and
interruption; see current [LiveKit tool speech documentation](https://docs.livekit.io/agents/logic/tools/definition/).
This API deliberately does not prescribe SDK call signatures.

### POST /calls/{id}/appointment/armed — agent, verified

Request: `{token: ID}`. Response:
`{status: "armed", armed_seq: integer >= 0, armed_at: UTC, expires_at: UTC, speak: string}`.
[Example](examples/booking-armed.json). Only the trusted adapter calls this after
uninterrupted read-back. Backend snapshots latest user sequence (0 if none);
any user turn stored since preview makes arming fail with `NOT_ARMED`. A retry
of an already armed token returns the original sequence and deadline, never
extends it. Expiry is 90 seconds after arming. A fresh read-back needs a fresh
preview. Interrupted speech never calls this route.

**Audio timing boundary:** receipt order alone cannot detect speech that began
during read-back but finalized after arming. Om must treat that speech as an
interruption, suppress arming or invalidate the attempt by obtaining a new
preview before another confirm. Do not call confirm while newer user speech or
a user-turn write is pending. This trusted adapter requirement needs a timing
test; a request boolean cannot prove that audio played.

### POST /calls/{id}/appointment/confirm — agent, verified

Request: `{token: ID}`. No member ID, slot override, text or yes flag.
Response: `{appointment: Appointment, speak: string}`.
[Example](examples/booking-confirmed.json). 201 for first commit, 200 for replay
of the same committed token with identical appointment and confirmation.

In one `BEGIN IMMEDIATE` transaction, the backend must:

1. Check for a booking already committed for this call/token and return that
   result first, including after expiry or finalization. This is a replay, not
   a second authorization. Tokens from another call never reveal that booking.
2. Require the current token, matching draft details/hash, and armed state.
   Resolve member from the verified call, not any caller-supplied identifier.
3. Read the newest stored **user** turn, ignoring later assistant turns. Require
   `seq > armed_seq`, receipt after arming, and both receipt and commit check
   before `expires_at`. Any newer no/change supersedes an older yes.
4. Classify that entire turn deterministically. Proposed first-build allowlist:
   `yes`, `yes please`, `confirm`, `book it`; lowercase, trim surrounding
   whitespace and terminal `.`, `!`, `?`, but no other word removal. Everything
   else fails closed as `NOT_CONFIRMED`. Never use substring matching or an LLM.
5. Recheck coverage on visit date, provider network, accepting new patients,
   primary-care/new-patient/in-person scope, latest offered slot, time window,
   and slot still open. Slot ID alone is insufficient.
6. Check interval overlap against booked appointments for **both** provider and
   member: `existing.start < chosen.end AND existing.end > chosen.start`.
   Mark slot booked and insert exactly one appointment, with consent turn and
   token provenance. Enforce the unique partial index on booked slot IDs.

Missing arming or no later turn gives `NOT_ARMED`; expired/invalidated token or
hash mismatch gives `STALE_CONFIRMATION`; a later non-yes gives `NOT_CONFIRMED`.
A conflict gives `SLOT_TAKEN` (slot/provider occupancy) or `OVERLAP` (member).
No failed confirm creates an appointment. A taken-slot/overlap/time/eligibility
failure invalidates this preview and clears the latest offers, retaining the
last availability query for the console. Recover by querying availability, choosing,
and reading back a new preview. A changed request also invalidates the token.
Concurrent user-turn writes and confirmation serialize on the same call/database;
Om must await queued user turns before starting confirm.

After a booking commits, draft-changing search, provider, availability, slot and
preview operations in that call return `NOT_BOOKABLE`: one booking per call in
this build. Follow-up, transcript and finalization remain available. A duplicate
confirmation reports the saved appointment; it does not run a new consent check.

`speak` is built from the committed appointment, includes the office phone and
confirmation digits spoken separately, and says the booking is simulated.
No “booked” speech before commit. Confirm retries always reuse the same token.

### GET /calls/{id}/appointment — agent, verified

Response: `{appointments: Appointment[], speak: string}`.
[Example](examples/appointments.json). Only bookings belonging to this verified
member **and this call**, with start at/after now, sorted by start. Empty means
`appointments: []` and “There is no upcoming simulated appointment saved for
this call.” This deliberately prevents a second call from exposing the first
call's bookings; internal overlap checks still span all calls for the member.

After timeout/connection loss, booking outcome is unknown. Read this endpoint
and/or retry confirm with the same token; never choose a replacement or announce
failure/success until reconciled. A missing HTTP response does not undo a commit.

## Console and handoff interfaces

These supporting contracts keep Siddhant's UI and Om's lifecycle hooks aligned.
They do not add backend implementation or expand the booking scope.

| Route / access | Request | Success response / rules |
| --- | --- | --- |
| `POST /calls/{id}/followup` — agent | `{category: TaskCategory, detail: string}` | 201 `{task: Task, speak: string}`; 200 for same call/category/detail retry. Packet is built from stored state, never invented by the model. Works unverified. |
| `POST /calls/{id}/finalize` — agent | `{}` | `{summary: Summary, speak: ""}`; wait for pending confirm to settle, then read committed rows. Repeat refreshes from rows. `unknown` if commit cannot be reconciled, never a guessed outcome. Marks call finalized. |
| `GET /calls/latest` — console | none | `{state: State | null, speak: ""}`; `null` before any call. Latest by creation time, tie by ID. Poll once/second; show call ID and reset panels when it changes. |
| `GET /tasks` — console | optional `?status=open` or `?status=completed`, omitted = all | `{tasks: Task[], speak: ""}`; sorted creation time then ID, newest first. |
| `POST /tasks/{id}/complete` — console | `{}` | `{task: Task, speak: ""}`; repeated completion returns same task. |
| `POST /admin/take-slot` — console | `{slot_id: ID}` | `{ok: true, slot_id: ID, state: "blocked", speak: ""}`; atomically marks open slot blocked with simulation reason; already occupied gives `SLOT_TAKEN`. Never fabricates another member's identity. |
| `POST /admin/reset` — console | `{}` | `{ok: true, speak: ""}`; atomically refuses `CALL_ACTIVE` while any call is live or commit pending. Clears calls, turns, drafts, appointments, events, tasks; restores fixture slot states. Preserves member/plan/provider fixtures. |

After finalize, reject new state-changing agent operations with `CALL_CLOSED`,
except late assistant transcript deliveries, repeat finalize and committed
confirmation replays. Read-only appointment reconciliation remains available.

`TaskCategory` is one of `caller_requested`, `knowledge_gap`, `verification_failed`,
`tool_failure`, `safety`, `policy_required`, `waitlist`.
`Task = {task_id: ID, call_id: ID, status: "open" | "completed", created_at: UTC,
completed_at: UTC | null, packet: Packet}`.
`Packet = {reference: string, category: TaskCategory, summary: string,
detail: string, caller_verified: boolean, plan: string | null,
already_tried: string[], suggested_next_action: string}`.
[Task example](examples/followup.json).

Code creates one task per escalation incident after three failed verifications,
two unanswered questions in a row, or two tool failures in a row. Thresholds
are consecutive, not lifetime counts; success resets the corresponding counter.
Verification locking is enforced by core. Ops owns other counters; see agreement
item 6 for the agent-to-ops signals still needing definition.

`State` has exactly the following required display fields (nullable objects
remain `null`, arrays remain `[]`, never stale values from a prior call):

| Field | Schema |
| --- | --- |
| `call_id`, `status`, `verified` | `ID`, `"live" | "finalized"`, `boolean` |
| `member` | `Member | null`; null before verification |
| `request` | `{version: integer >= 0, specialty: "primary care" | null, zip: ZIP | null}` |
| `turns` | `Turn[]`, sorted seq; verification values masked for display |
| `providers`, `excluded`, `selected`, `evidence` | `Provider[]`, `Excluded[]`, `ID | null`, `Evidence[]` |
| `offered_slots` | `Slot[]`, latest availability only |
| `draft` | `null` or `{slot_id: ID, revision: integer, status: "slot" | "preview" | "armed" | "booked", armed_seq: integer | null, expires_at: UTC | null}`; invalidated/expired uncommitted drafts project as null, never imply a hold |
| `appointment` | `Appointment | null`; only a committed row produces a booking card |
| `day_slots` | `DaySlot[]`; selected provider and chosen slot's date, else first offered date, else last availability query's `date_from`, else `[]` |
| `tasks`, `summary`, `events` | `Task[]`, `Summary | null`, `string[]` ordered event names |

`DaySlot = {slot_id: ID, starts_at: UTC, ends_at: UTC, text: string,
state: "open" | "booked" | "blocked", offered: boolean, selected: boolean}`.
Offered/selected are annotations, not reservations. All state fields are one
consistent database snapshot. No token/hash or unverified member data in state.
Summary confirmation is populated only from a committed appointment row.

See `examples/state-*.json` for idle, unverified, verified, offered, preview,
armed, conflict, booked, finalized and follow-up console responses.

## Decisions to agree before implementation

1. **Wire format and names:** flat successes, `{state: ...}` polling wrapper,
   `appointments` as the SQL table for bookings, added `plans` and
   `provider_networks` tables. Keep section 8's paths. `/turn` replaces the older
   `/transcript` reference; add `client_turn_id` for delivery retries.
2. **Consent boundary:** approve the strict yes allowlist, conservative expiry
   check at commit, and preview/arming retry rules. Om must prove early-started
   speech cannot arm/confirm, even if its finalized transcript arrives later.
3. **Local console access:** agree loopback + same-origin proxy restrictions for
   the prototype. A dashboard on another machine needs an explicit access scheme.
4. **Dates:** approve the two-candidate weekday rule, inclusive 14-calendar-day
   Eastern date window, and coverage-by-visit-date behavior. Examples freeze the
   backend clock at November 6, 2026, 4 PM Eastern; fixtures must be reseeded later.
5. **Call isolation/retries:** appointments are call-scoped, one booking per call
   for this build, and identical committed-token retries work after finalize.
   Arbitrary later calls do not list prior appointments; overlap still spans them.
   Verification is synthetic last-four + month matching, not strong identity.
6. **Ops signals:** Siddhant and Om still need to agree how two unanswered
   questions and two client-side tool failures are reported to ops code. This
   contract defines the tasks and counters but intentionally adds no speculative
   event-ingestion API. Those escalation signals must be settled before wiring
   that behavior. Core verification locking can be implemented independently.

These are proposed defaults, not claims of prior team approval. Scope overrides
in the plan take precedence over its older specialist/week-calendar examples.
