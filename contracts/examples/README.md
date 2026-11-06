# Synthetic response fixtures

These are complete API response bodies for Om's fake backend and Siddhant's
console development, not real member or appointment data. All `state-*.json`
files use the `GET /calls/latest` envelope `{ "state": ..., "speak": "" }`.
Use `response.state` for rendering. Tokens in transport fixtures are obvious
demo placeholders and never appear in state or speech.

Freeze the example backend clock at **November 6, 2026, 4 PM Eastern**
(`2026-11-06T21:00:00Z`), advancing it through the illustrated turns. The chosen
slot is November 13 at 3 PM Eastern (`20:00Z`), exactly 30 minutes long.
Examples expire as live schedule data; runtime seeds must be relative to the
backend clock. They are not input for a real provider schedule.

| Response files | Route | HTTP |
| --- | --- | --- |
| `call-created.json` | `POST /calls` | 201; replay 200 |
| `now.json` | `GET /now` | 200 |
| `turn-stored.json` | `POST /calls/c_01/turn` | 201; replay 200 |
| `verified.json` | `POST /calls/c_01/verify` | 200 |
| `providers.json` | `POST /calls/c_01/providers` | 200 |
| `provider-selected.json` | `POST /calls/c_01/select` | 200 |
| `dates.json` | `POST /calls/c_01/dates` | 200 |
| `availability.json` | `POST /calls/c_01/availability` | 200 |
| `slot-selected.json` | `POST /calls/c_01/slot` | 200 |
| `booking-preview.json` | `POST /calls/c_01/appointment/preview` | 200 |
| `booking-armed.json` | `POST /calls/c_01/appointment/armed` | 200 |
| `booking-confirmed.json` | `POST /calls/c_01/appointment/confirm` | 201; same body on 200 replay |
| `appointments.json`, `appointments-empty.json` | `GET /calls/c_01/appointment` | 200 |
| `followup.json` | `POST /calls/c_01/followup` | 201; replay 200 |
| `tasks.json` | `GET /tasks` | 200 |
| `finalized.json` | `POST /calls/c_01/finalize` | 200 |
| `state-*.json` | `GET /calls/latest` | 200 |
| `error-*.json` | Corresponding route from api.md | See errors.md; these are non-2xx bodies |

The main call's display progression is `state-unverified`, `state-verified`,
`state-offered`, `state-preview`, `state-armed`, `state-booked`, `state-finalized`.
`state-idle` is the console before any call. `state-conflict` and `state-followup`
are alternative branches, not later stages of that successful booking. After
the conflict, refresh availability and obtain new consent before booking a
different slot. A preview is never a hold. Only `state-booked` and
`state-finalized` contain a committed appointment.

Provider fixtures use section 9's Maya/METRO plan: Haddad and Westside are eligible;
Park is excluded for not accepting new patients; Liu is out of network. The
coverage-ended response is a separate Devon fixture. The lock response belongs
to separate call `c_02` and reveals no member data. Follow-up is caller-requested,
so it stays within the first build rather than relying on a stretch specialist.

The stored consent example is `Yes please.` (turn 5), later than `armed_seq: 3`.
Turn 4 is assistant speech and does not change the user-sequence snapshot. The
backend retains original turns; the console examples redact verification data.
`client_turn_id` is supplied by the adapter on writes and is not part of the
display projection.

`care-journeys.json` is a separate synthetic seed manifest for the schema-v2 data
extension, not an HTTP response or `State` object. It includes initial plan,
provider, member, appointment, referral and relevant slot rows plus 13 named
specialist/rescheduling cases. See [care-journeys.md](../care-journeys.md) for
regeneration, route status and the Om/Sid handoff. Its printed member cards must
not be exposed as unverified console state.
