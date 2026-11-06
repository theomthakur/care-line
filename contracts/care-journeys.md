# Specialist and rescheduling data extension

Implemented November 6, 2026: SQLite schema v2, automatic migration, Pydantic
extension models, provider/member fixtures, and an opt-in care-history dataset.

**This is the data foundation. Specialist booking and rescheduling HTTP routes
are not implemented by this change.** The mounted routes in `api.md` continue to
book primary care only. The route additions below are an integration proposal,
not endpoints Om can call yet. Agent and dashboard code are unchanged.

## Run the synthetic dataset

A demo database has been generated at `data/memberguide-care-demo.db`. The
versioned, reproducible fixture manifest is [examples/care-journeys.json](examples/care-journeys.json).
It contains synthetic verification cards, plans, providers/networks, completed
and upcoming appointments, referrals, relevant slots, and 13 named cases. It is
seed data, not a console-state or live API response.

```sh
uv run python -m backend.core.seed --date 2026-11-06 \
  --db data/memberguide-care-demo.db --care-journeys \
  --export contracts/examples/care-journeys.json

# Start the service against that database using the existing private key config.
MEMBERGUIDE_DB_PATH=data/memberguide-care-demo.db \
  uv run uvicorn backend.main:app --env-file .env.memberguide --host 127.0.0.1 --port 8000
```

Keep the same private key in the agent adapter. Do not commit the SQLite file or
credentials. The current server still exposes only the existing PCP operations;
the added rows can be inspected by backend queries or used as UI fixture data.
The old call-scoped appointment endpoint will not return these imported rows.

Normal startup adds the extra provider/member fixtures but does not install
appointment history. `--care-journeys` explicitly adds that history. Installation
refuses live calls and refuses to overwrite occupied appointment slots. A repeat
with the same demo date returns the saved original manifest without undoing later
bookings, rescheduling or referral changes. Use a fresh database path for a new
demo date. The printed manifest describes the initial fixture state; it is not a
live export of subsequent changes. Dates use Eastern business days and UTC slot
instants. These plan/coverage fixtures are for the 2026 demo year.

## Cases for Om and Sid

All IDs, identities, recommendations and bookings are synthetic. Verification
cards belong on the printed demo card, never in unverified console state.

| Member | Verification | Plan | Available cases |
| --- | --- | --- | --- |
| Maya T. (M1) | 4417 / April | Gold, METRO | Completed PCP visit; reported dermatology recommendation; formal referral not required; PCP and specialist rescheduling |
| Riley C. (M2) | 2261 / June | Basic, VALUE | Completed PCP visit; verified cardiology referral through Nov 13; PCP and specialist rescheduling |
| Devon C. (M3) | 8832 / September | Basic, VALUE | Existing ended-coverage case; do not use to demonstrate a missing referral alone |
| Tessa B. (M4) | 7734 / February | Basic, VALUE | Active coverage, completed PCP visit, missing specialist referral |
| Jordan B. (M5) | 6652 / November | Basic, VALUE | Active coverage; expired dermatology referral and revoked cardiology referral |

| Rescheduling case | Original fixture appointment | Doctor | Original (Eastern) | Available replacement (Eastern) |
| --- | --- | --- | --- | --- |
| Maya PCP | FIX-MAYA-PCP-BOOKED | P2, Dr. Omar Haddad | Nov 10, 9:30 AM | Nov 11, 9:30 AM |
| Riley PCP | FIX-RILEY-PCP-BOOKED | P4, Westside Family Medicine | Nov 12, 10:00 AM | Nov 13, 10:00 AM |
| Maya specialist | FIX-MAYA-SPECIALIST-BOOKED | P8, Dr. Aaron Shah, dermatology | Nov 12, 1:00 PM | Nov 13, 1:00 PM |
| Riley specialist | FIX-RILEY-SPECIALIST-BOOKED | P6, Dr. Nina Rao, cardiology | Nov 10, 11:00 AM | Nov 11, 2:00 PM |

Each of these four cases also has an occupied alternative slot in the manifest.
A thirteenth case moves Riley's specialist visit to Nov 16, after the referral
expires: backend policy must refuse it and retain the original appointment.

Provider additions: P7 is a METRO cardiologist, P8 is a dermatologist in both
networks, and P9 is a cardiologist in both networks who is not accepting new
patients. Existing P5 still has no availability; P6 is out of network for Maya.
This preserves distinct examples of eligibility, network exclusion, refusal of
new patients and no availability.

## Data model changes

`Database.initialize()` upgrades the previous unversioned/v1 schema to v2 in one
transaction. It copies all existing columns, including original consent turns,
bookings, current drafts and tokens. It checks all foreign keys before commit
and rolls back schema and data together on failure. Connections enable foreign
keys again after the migration. The migration does not install care history.

| Table | Added or changed fields | Purpose |
| --- | --- | --- |
| plans | specialist_referral_required | Structured demo policy; Gold false, Basic true; plan_sections still supplies spoken evidence |
| calls | specialty supports primary care/cardiology/dermatology; operation; reschedule_appointment_id | A new call can represent booking or movement of an existing member-owned appointment |
| drafts | operation; reschedule_appointment_id; source_appointment_version; referral_id | Bind a proposed move to the source appointment/version and referral |
| appointments | status; source; version; referral_id; replaces_appointment_id; optional voice provenance for imports | Preserve completed visits and old/new appointment history without inventing consent |
| referrals | member; referring PCP/visit; specialty; status; validity dates; source | Separate recommendations from verified formal referrals; maintain the connection to the completed PCP visit |
| demo_fixture_sets | demo_date; manifest_json | Install history once and preserve later user actions on reseed |

Appointment statuses are `booked`, `completed`, `cancelled`, `rescheduled`.
`cancelled` is storage support only; no cancellation flow is added. A successful
reschedule is designed to keep the old row as `rescheduled` and append a new
`booked` row whose `replaces_appointment_id` points back to it. The old slot is
released. The unique successor link and active-slot uniqueness are DB safeguards.
Cross-member referral and rescheduling links are rejected by composite foreign
keys. Provider matching, source status, timing and overlap remain backend rules.

`source=voice` continues to require a call, draft and consent turn.
`source=synthetic_fixture` requires all three to be null. Imported appointments
have `MG-DEMO-*` references; they do not claim a real booking or a live caller's
consent. All initial visits remain `new_patient`, in-person, 30 minutes; the
completed PCP and subsequent new-patient PCP appointment use different doctors.
Rescheduling preserves the source visit type/modality; returning-patient booking
and changing doctors during a reschedule are separate future features.

Referral status is `reported`, `verified` or `revoked`. Expiry is calculated from
the proposed visit's Eastern date, not encoded as a permanent status. A verified
record requires a referring PCP/visit and validity dates. A caller report may
lack those identifiers and cannot be marked verified. A PCP visit alone does not
create a referral. Plan evidence must use `GOLD-REF`/`BASIC-REF` for specialists;
never describe specialist visits using a PCP preventive-benefit passage.

The new wire types are in `backend/core/models.py`: `Specialty`,
`AppointmentStatus`, `CareAppointment`, `CarePlan`, `Referral`,
`ReferralEligibility`, `RescheduleRequest`, and `CareAppointmentsReply`.
Existing booking response shapes remain unchanged. `CareAppointment` exposes the
actual status, specialty, provenance, version and predecessor link. The existing
`appointment_view()` is only for the existing booking flow and must not be used
unchanged to project completed/rescheduled history: it currently labels results
`booked`. Build a projection for `CareAppointment` before exposing history.

## Core backend work still required (Aneesh)

These changes must land before enabling the new voice/UI actions. Do not move
these checks into Om's prompt or Sid's browser.

1. Generalize provider search/selection and `check_provider()` to the requested
   specialty; choose the correct plan passage. Preserve network/new-patient rules.
2. Add member-scoped appointment lookup after verification, using the current
   call's bound member. Keep the existing call-scoped endpoint's meaning.
3. Resolve referral eligibility from structured plan policy plus a verified,
   matching-specialty, non-revoked referral valid on the visit date. Return the
   evidence passage and an explicit eligibility result; use `REFERRAL_REQUIRED`
   for missing/expired/revoked required referrals, preserving any original booking.
4. Bind the chosen source appointment to the new call. Require a future, booked,
   member-owned appointment. In the first version keep its provider, visit type
   and modality. Prevent generic booking tools from bypassing that binding.
5. Extend preview/arming/confirmation to bind operation, original appointment ID,
   source version, referral and replacement details into the confirmation hash.
   Read back both original and replacement appointments. An old yes/token must
   never authorize a move. Preserve strict consent and playout/ingress barriers.
6. Commit the move under the shared write barrier and one `BEGIN IMMEDIATE`:
   recheck source status/version, new slot, network, referral on the new date,
   coverage, time and overlaps; exclude only the source appointment from the
   member-overlap check. Claim the new slot, mark the old row rescheduled and
   increment its version, insert the successor, release the old slot and record
   events. Any failure rolls everything back. A duplicate confirmation returns
   the saved replacement without performing another move. Replaying an older
   booking token after a later move must report truthful current status.
7. Add API/concurrency tests: PCP and specialist moves, rejected/early consent,
   source changed on another call, taken replacement, expired referral on the
   replacement date, cross-member access, overlap, retries and rollback.

Suggested route contract, **not mounted yet**:

| Route | Purpose / response |
| --- | --- |
| GET /calls/{id}/member-appointments | Verified member's upcoming booked appointments; CareAppointmentsReply; empty speak/selection prompts as appropriate |
| POST /calls/{id}/reschedule | RescheduleRequest `{appointment_id}`; bind source and return its CareAppointment, specialty and operation |
| POST /calls/{id}/providers | Existing route generalized to specialty; add ReferralEligibility alongside applicable plan evidence |
| Existing availability and slot routes | Replacement options for the bound source's provider |
| Existing preview / armed / confirm routes | Extend internally for operation=reschedule; new read-back/consent; confirmation returns the committed successor plus original ID/status |

Lock exact response changes in `api.md` and add API examples when these routes
are implemented. Until then, the old contract is authoritative for live calls.

## Om: voice agent and adapter changes

- Add a specialist branch: confirm the specialty recommended by the PCP, verify
  the member, and use backend eligibility and evidence. Keep caller-reported
  recommendations separate from a formal referral. Do not choose a specialty
  medically or promise specialist coverage from the PCP preventive passage.
- Add a reschedule intent. Load the member's appointments from the new lookup,
  ask which one when there are several, bind it using the reschedule route,
  and gather a replacement date/time for the same provider. Do not ask the LLM
  to invent appointment IDs or call the old call-scoped lookup for prior visits.
- Keep opaque IDs, token, operation and predecessor/version in adapter state.
  Speak the backend-generated old/new read-back, finish uninterrupted playout,
  arm, await a new finalized affirmative user turn, then confirm. A spoken
  "move it" before the read-back is not consent. On interruption/correction,
  invalidate/reprepare; on a taken slot, explain that the old booking is intact.
- Reconcile an uncertain outcome with the saved operation/token. Never cancel
  first or issue a second independent booking to emulate rescheduling. Speak
  only the committed replacement confirmation. Keep replies short and EndCallTool.
- For referral failure, offer a saved follow-up packet through the existing
  follow-up integration; do not claim that a referral request was sent unless
  the backend saved it. Use the current `policy_required` task category.
- Before changing instructions/tools, write scenarios for the four positive
  moves, missing/expired/revoked referral, replacement conflict, and referral
  expiry on the new date. Start with the text debugger, then run one scenario at
  a time per repo instructions. These data tests do not certify a voice flow.

LiveKit's [tool loop design](https://docs.livekit.io/agents/logic/tools/design/)
describes gating critical writes with explicit read-back and confirmation. Keep
the repository's stricter backend-owned consent checks; don't replace them with
a model-supplied confirmation flag.

## Sid: backend projection and dashboard changes

- Use the same `request.app.state.db` and one consistent snapshot. After member
  verification, project member appointment history separately from this call's
  committed action. Never show a fixture booking as a new action on the current
  call or infer visit completion from an appointment's scheduled end time.
- Add specialty, operation and source appointment to request state. Show the
  completed PCP visit and recommendation/referral status with the cited plan
  passage. Display reported, verified, expired and revoked states distinctly.
- Add original and proposed appointment cards during a move. The original
  remains visibly booked until commit; then show it as rescheduled, the new card
  as booked, and the released/occupied slot states from backend data. Display
  an old-to-new history link using `replaces_appointment_id`.
- Use CareAppointment's real status and version. Keep fixture provenance visible
  in demo/operator details, and never reuse the v1 hardcoded `booked` projection
  for historical visits. No tokens, hashes or verification answers in state.
- Update summaries and follow-up packets: distinguish a new booking, a move,
  unchanged original after a conflict, and referral follow-up. Build outcomes
  from committed rows/events. Unsupported API actions should remain unavailable
  until the core routes land.
- Update reset for the new foreign keys. A blind `DELETE FROM appointments` will
  fail against referral/lineage references and would lose the history needed for
  these demos. Safest initial reset: with no live call or pending write, create
  and seed a fresh demo DB, then restart the shared backend. An eventual in-place
  reset must clear call/draft source references, remove voice replacements in
  dependency order, restore fixture statuses/versions, restore original fixture
  slot occupancy and replacement slots, and preserve referrals/manifest. Normal
  reseeding intentionally does not do this reset.
- Use the JSON manifest to build UI fixtures now. Read live schedule/outcomes
  from backend state once integrated; the exported manifest stays a baseline.
