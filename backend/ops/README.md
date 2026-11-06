# backend/ops

Console read model, handoff packets, summaries and demo/admin routes (plan section 17). It reads the rows core writes (`contracts/schema.sql`) and makes no booking decisions.

Mount in the app: `from backend import ops; ops.install(app)` (adds the router and the contract error envelope). It opens SQLite through `app.state.db_path` or `app.state.get_conn`.

| Route | Access | Notes |
| --- | --- | --- |
| `GET /calls/latest` | console | `{state, speak}`; `state` is null before any call; verification answers masked |
| `GET /calls?recent=20` | console | `{calls: CallSummary[]}`: every live call (newest first), then the most recent finished calls (0-100). One snapshot, no secrets |
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
