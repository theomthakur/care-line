# MemberGuide review: act on these before building

Reviewed 6 November 2026 against the 27-page final plan, seminar notes and Take2 starter main commit `27eef97bb40c7fde11ae1b335148796ef2c1344a`. Review only: no MemberGuide implementation, calls or simulations were run.

## Decision

Keep MemberGuide. The idea fits the real-phone task and scoring. Build the primary-care booking path first; the full plan is too large to treat every item as mandatory by 6:00. Nothing custom is assumed prebuilt. Reusing the supplied working starter and example patterns is expected.

The kit weights completion 30, difficult caller 25, natural conversation 20, explanation/design 15 and bonus 10. Protect the first 75 points before expanding features. Its milestones are 5:00 talking, 6:00 calling and 7:00 demo-ready; your 6:00 feature freeze is a useful internal target, not an organizer submission deadline.

## Correct before implementation

| Priority | Finding | Required change / proof | Owner |
| --- | --- | --- | --- |
| P0 | Confirmation reads asynchronously forwarded transcript rows. A tool may run before the latest yes is saved, or after an old yes while a newer refusal is still in flight. | Persist finalized critical user turns in order before tool execution. Bind confirmation to the current turn ID and preview hash; fail closed on missing/reordered turns. Keep display-only telemetry asynchronous. Test delayed, duplicate and reordered transcript writes. | Om + Aneesh |
| P0 | Preview creation is earlier than completed spoken read-back. A yes after preview creation can still arrive before the caller heard the full proposal. | Arm confirmation only after actual read-back playback completes without interruption. Record the preview and completed read-back IDs plus the later user-turn sequence. An interrupted read-back, correction or new preview invalidates consent. An exact yes allowlist must reject questions and qualification, not merely detect the word yes. | Om + Aneesh |
| P0 | Forty-minute appointments on a thirty-minute grid overlap across distinct slots. Unique slot IDs do not prevent one doctor being booked at 2:30–3:10 and 3:00–3:40. | Check interval overlap for both provider and member inside the transaction. Alternatively, use one explicitly stated fixed duration/compatible grid for the MVP. Test different slot IDs with overlapping intervals. | Aneesh |
| P0 | The plan says the safety screen runs before any model call, but the starter enables speculative/preemptive generation. | Disable preemptive generation initially if making that claim, or screen before model dispatch and verify the ordering. A turn-completed hook alone does not prove zero earlier inference. Do not call phrase matching a clinical triage guarantee. | Om |
| P1 | Patient status is requested after provider selection, while search already filters new-patient eligibility. Returning callers can lose valid options. | MVP: explicitly support new patients only. If retaining both, obtain visit/patient status before filtering and include it in draft invalidation. | Om + Aneesh |
| P1 | Confirm lists token/hash/slot checks but not every eligibility check at commit. | Recheck verified member, coverage applicable to appointment date, provider network/eligibility, referral if supported, and visit type inside commit. A guessed ID cannot bypass search. | Aneesh |
| P1 | `lookup_plan_information` has no matching route or exact request/response contract. Transcript ordering/read-back completion fields are also absent. | Specify these before independent work. Prefer folding returned plan evidence into provider selection instead of adding another tool. | All |
| P1 | Devon has expired coverage and no referral, so he cannot independently exercise missing-referral behavior. | Test an active Basic member without a referral separately, or cut specialists/referrals from the first build. Restore a known fixture between cases. | Aneesh |
| P1 | Summary finalization can race a booking that survives caller disconnect. | Finalize after pending commit resolves, or mark result unknown and reconcile from the database. Repeated finalize calls must refresh from committed state. Keep receipt/booking lookup available after timeout. | Om + Siddhant |
| P1 | Display/admin routes need a clear access boundary; reset can erase work during a call. | Bind locally; keep the agent key out of browser code. Protect operator mutations and reject reset while a call/write is active. Choose the call explicitly on the console. | Aneesh + Siddhant |

## Reduce coordination overhead

Use three owner branches: voice, booking-core and console. Use small commits and merge at checkpoints. Eleven branches/worktrees plus nine simultaneous writers adds integration work during a two-hour build. Within each owner's files, keep one writing assistant active; use other assistants for bounded reviews or tests.

Consent-critical transcript storage belongs with the booking core, even if Siddhant owns the dashboard transcript. This is a backend dependency. Agree its ordered-write contract first; tests that insert transcript rows directly cannot prove the actual voice integration works.

Aneesh still has the heaviest dependency path. Equal task counts do not make equal implementation effort. Cut features before trying to redistribute more interfaces.

## Keep by 6:00

- One real inbound phone number, one LiveKit agent and the kit's turn handling.
- One synthetic member/plan, primary care and a few known providers, including an excluded provider.
- Verification, network filtering and ZIP correction.
- Available demo slots, interrupted/corrected read-back handling, explicit consent and atomic booking.
- One confirmation number matching the stored appointment and screen.
- A simple console with transcript, provider options, booking card and a code-built summary or follow-up.
- An honest response when tools fail or the request cannot be completed.

Prefer six model-facing tools: verify, search providers, list slots, prepare booking, confirm booking and request follow-up. Initialization, transcript writes, clock handling and finalization can be internal operations. Return concise evidence and canonical spoken dates from those tools.

## Cut first

Cancel/reschedule; specialist/referral workflows; multiple plans/members; telehealth; reminder texts; hold expiry; full week calendar; arbitrary provider-name fuzzy search; general benefit side questions; extra automation around escalation. Keep the slot-conflict demo only after the ordinary booking call passes. A small appointment card is sufficient until then.

Do not present the normal call as a stress test with every correction and a collision. Make the normal call short; use the conflict as the single distinctive trap, and let the judge supply the other difficulty.

## Test realistically

The PDF improved thirty phone tests to twelve, but twelve full calls plus six text tests and bug fixing is still too much for Siddhant in forty minutes.

Use six focused real-phone checks: normal completion; correction; interruption/negative confirmation; slot conflict; silence; tool failure/unknown outcome. Run multiple assertions per call where sensible. Include sensitive-request refusal in those calls. Move remaining logic to automated unit tests or text debugger; omit stretch-only scenarios when the feature is cut. Om and Aneesh should take most text runs while Siddhant logs phone outcomes.

Keep both consent timing tests: yes before read-back ends and yes-with-a-change. Add two synthetic phone calls arriving concurrently only if the number/project permits it; the database concurrency test is still mandatory.

The starter currently has two silence check-ins before goodbye. Section 11 test 13 expects one; pick one policy and match code/test/pitch. Do not run a two-second pause test after blindly reducing endpointing to 1.5 seconds based on somebody else's measurements. Test your own audio first.

## Honest demo language

Say that booking uses a simulated provider schedule before confirming the first appointment, not only if asked. The greeting currently mentions made-up data but does not specifically disclose the schedule; the system prompt's "if asked" wording conflicts with section 1.

Use "verification against synthetic demo records," not a claim of strong real-member authentication. Never claim HIPAA compliance, clinical triage reliability or access to real provider schedules. Keep the existing no-diagnosis/no-cost-guarantee boundaries.

## Suggested ownership

- **Om:** phone, conversation, ordered user turns, completed read-back and tools.
- **Aneesh:** schema, verification, provider/slot rules, consent records and atomic booking.
- **Siddhant:** console, appointment card, summary/follow-up and phone test log.

At 5:00 require a complete integrated text booking against real backend state. At 5:30 require the first actual phone booking. At 6:00 freeze features; spend the last hour on phone behavior, defects and rehearsal. If booking is still broken at 5:30, deliberately redefine the demo task as provider search plus a saved follow-up request; stop claiming booking completion.

## Sources

- `MEMBERGUIDE-FINAL-PLAN.md`, sections 1, 5, 7–12 and 18–21; corresponding 27-page PDF.
- `SEMINAR-NOTES-2026-11-06.md` (transcript-derived notes, not independently confirmed company claims).
- [Take2 starter README and source](https://github.com/vramesh1/take2-voice-agent-hackathon-starter).
- [LiveKit preemptive generation](https://docs.livekit.io/agents/multimodality/audio/).
- [LiveKit pipeline hooks](https://docs.livekit.io/agents/logic/nodes/).
- [LiveKit function tools and interruption handling](https://docs.livekit.io/agents/logic/tools/definition/).
