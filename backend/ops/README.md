# backend/ops

Console read model, handoff packets, summaries and demo/admin routes (plan section 17). It reads the rows core writes (`contracts/schema.sql`) and makes no booking decisions.

Mount in the app: `from backend import ops; ops.install(app)` (adds the router and the contract error envelope). It opens SQLite through `app.state.db_path` or `app.state.get_conn`.

| Route | Access | Notes |
| --- | --- | --- |
| `GET /calls/latest` | console | `{state, speak}`; `state` is null before any call; verification answers masked |
| `GET /calls?recent=20` | console | `{calls: CallSummary[]}`: every live call (newest first), then the most recent finished calls (0-100). One snapshot, no secrets, **no transcript text**. Also closes calls that went quiet without being finalized (see below) |
| `GET /calls/{id}/summary` | console | `{status, summary, details}`: the stored outcome plus facts re-read from saved rows (verification, provider, booking, problems, follow-ups, next action). Kept off `/state` so that stays exactly the contract's `State` |
| `GET /calls/{id}/state` | console | the same `State` as `/calls/latest`, for one call; unknown id is 404 `CALL_NOT_FOUND`, never "the latest" |
| `GET /tasks?status=`, `POST /tasks/{id}/complete` | console | complete is idempotent |
| `POST /admin/take-slot` | console | blocks one open slot as a simulated caller; does not touch drafts |
| `POST /admin/reset` | console | `CALL_ACTIVE` while any call is live or a commit is pending |
| `POST /calls/{id}/followup`, `/finalize` | agent (`X-Agent-Key`) | packet and summary built from stored rows |

Library hooks for other owners: `tasks.create_task(conn, call_id, category, detail, dedupe_key)` (core can use it for the `verification_failed` lock), `summary.pending_commit` (core registers a "confirm in flight" check), `escalation.record_signal` (not wired to a route yet: contract agreement item 6).

Dev only: `dev_seed.py` builds a database from the schema with synthetic fixtures and writes a call at any stage; `dev_app.py` serves it.

```bash
uv run pytest tests/ops -q
```

## Summaries and calls that never hung up cleanly

The voice agent finalizes a call from its shutdown hook. If that hook never runs (worker killed, line dropped), the call used to stay `live` forever with no summary. `GET /calls` now closes any live call with no turn or event for `CARELINE_ABANDON_AFTER_S` seconds (default 300, the same window core uses for "stale") by running the normal finalize on its saved rows and marking the stored summary `ended_reason: "dropped"`. A call whose confirmation is still being committed is left alone. Nothing is guessed: a booked call reads booked only because an appointment row exists.

Every console response carries `Cache-Control: no-store`.
