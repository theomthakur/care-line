# backend/ops

Console read model, handoff packets, summaries and demo/admin routes (plan section 17). It reads the rows core writes (`contracts/schema.sql`) and makes no booking decisions.

Mount through `backend.main.create_app()` so authentication, organization scoping,
error envelopes, and ordered writes are installed together. A custom host using
`ops.install()` must also provide `app.state.auth`, `security`, and the shared
`db`; mounting a router alone never grants access.

| Route | Access | Notes |
| --- | --- | --- |
| `GET /calls/latest`, `/calls/history`, `/calls/{id}/state` | operator | `{state, speak}`; verification answers masked |
| `GET /providers/directory` | operator | provider availability projection |
| `GET /tasks?status=`, `POST /tasks/{id}/complete` | operator | complete is idempotent |
| `POST /admin/take-slot` | admin, synthetic | blocks one open slot as a simulated caller |
| `POST /admin/reset` | admin, synthetic | `CALL_ACTIVE` while any call is live or a commit is pending |
| `POST /calls/{id}/followup`, `/finalize` | agent + owned call capability | packet and summary built from stored rows |

Library hooks for other owners: `tasks.create_task(conn, call_id, category, detail, dedupe_key)` (core can use it for the `verification_failed` lock), `summary.pending_commit` (core registers a "confirm in flight" check), `escalation.record_signal` (not wired to a route yet: contract agreement item 6).

Dev only: `dev_seed.py` builds a database from the schema with synthetic fixtures and writes a call at any stage; `dev_app.py` serves it. Both refuse production. Database directories must be owner-only. The standalone app defaults to `/tmp/careline-dev/memberguide.db`.

```bash
uv run pytest tests/ops -q
```

## Access control update

Console routes now require an organization-scoped operator credential; agent
follow-up/finalize routes also require the call capability. Admin routes require
an admin credential and are disabled in production. See
[BOOKING-SECURITY.md](../../docs/BOOKING-SECURITY.md) for setup and migration.
