# Integration handoff: console + ops (Siddhant) → Aneesh, Om

Branch `feat/siddhant-console-handoff`, draft PR #1. Contracts are unchanged: `contracts/` is byte-identical to `origin/booking-core` (c039929). I touched nothing in `src/`, `backend/core/`, `data/` or `contracts/`.
As of this note, `booking-core` has contracts only (no core code yet), so ops has only run against `contracts/schema.sql` plus a dev seed.

## 1. Route ownership (please confirm)
| Route | Owner | Note |
| --- | --- | --- |
| `GET /calls/latest`, `GET /tasks`, `POST /tasks/{id}/complete`, `POST /admin/take-slot`, `POST /admin/reset` | **ops** | console routes, no agent key |
| `POST /calls/{id}/followup`, `POST /calls/{id}/finalize` | **ops** (proposed) | the contract lists them under "Console and handoff interfaces"; **Aneesh: don't also build them** or tell me to drop mine |
| everything else in `contracts/api.md` (`/calls`, `/turn`, `/verify`, providers, select, dates, availability, slot, preview, armed, confirm, appointment, `/now`) | **core** | ops never writes these rows |

Duplicate paths would silently shadow each other, so whoever mounts both routers should fail loudly on a duplicate.

## 2. Mounting and DB connection (Aneesh, owner of `backend/main.py` and `db.py`)
```python
from backend import ops
ops.install(app)   # adds the router AND the contract error envelope {error, speak}
app.state.db_path = DB_PATH          # or: app.state.get_conn = lambda: your_connection()
```
- Ops opens its own short-lived connection per request with `PRAGMA foreign_keys=ON`, autocommit, explicit `BEGIN` / `BEGIN IMMEDIATE`. If you pass `get_conn`, return an **autocommit** (`isolation_level=None`) connection, because ops manages transactions itself.
- `install` registers handlers for `HTTPException` and `RequestValidationError`. They also apply to core routes in the same app, which is what `errors.md` wants (no framework validation arrays).
- Tests and a throwaway DB: `backend/ops/dev_seed.py` (dev only, uses `contracts/schema.sql`). Replace it with `data/seed.py` when it exists.
- Agent routes read `AGENT_KEY` (default `dev-agent-key`, same as Om's client).

## 3. Pending-commit hook (Aneesh)
`finalize` must wait for an in-flight confirm. Ops cannot know about it, so core registers a function:
```python
from backend.ops import summary
summary.pending_commit = lambda call_id: <True while a confirm for call_id is running>
```
Finalize polls it for up to `summary.PENDING_WAIT_S` (3 s), then reads committed rows. If it is still pending, the outcome is `unknown` with `confirmation: null`. `/admin/reset` also refuses (`CALL_ACTIVE`) if it returns True for any call. Until core registers it, the default is "nothing pending".
Also: for a verification lock, call `ops.tasks.create_task(conn, call_id, "verification_failed", detail, dedupe_key)` inside core's lock transaction (it reuses an open transaction). It is idempotent per `(call_id, dedupe_key)`.

## 4. Escalation signals (Om + me; contract agreement item 6, still open)
`ops.escalation.record_signal(conn, call_id, signal)` implements the consecutive counters (2 unanswered, 2 tool failures; success resets; one task per streak). **No route calls it**, because the contract defines no ingestion API and I won't invent one. Decision needed from Om and Aneesh: either
(a) a small agent route `POST /calls/{id}/signal {signal}` owned by ops (my suggestion, ~10 lines), or
(b) Om counts client-side and calls `/followup` with `tool_failure` / `knowledge_gap` himself.
Until then, no automatic escalation fires. Don't promise it in the pitch.

## 5. What a real end-to-end test needs
1. Core exists: schema loaded, fixtures seeded (`data/seed.py`), core routes mounted with `ops.install(app)` in one process that owns SQLite.
2. Console: `cd frontend && npm run dev` (proxies `/calls /tasks /admin` to `127.0.0.1:8000`; no key in the browser). Port 8000 must be free (Om's `preview/server.py` also binds it).
3. Agent: `USE_FAKE_BACKEND=0`, `BACKEND_URL=http://127.0.0.1:8000`.
4. Call c_01 end to end and check that the screen matches the database: transcript, member (masked), providers + excluded reasons, plan passage, armed read-back, **conflict button during the read-back** (ops only blocks the slot; core's confirm must return `SLOT_TAKEN` and void the preview), confirmation number equal to the `appointments` row, summary, hang-up after yes (finalize waits for the commit), backend stopped mid-call (console shows disconnected, never success).
5. `/admin/reset` refused while a call is live, works after finalize.

### Payload mismatches I saw between Om's client (`om/integration`) and `contracts/api.md`
Not mine to change; for Om and Aneesh to settle. If core follows the contract strictly (it rejects unknown fields), these calls will fail:
- `POST /turn` sends `{role, text}`; contract also requires `client_turn_id`.
- `POST /verify` sends `birth_month` as a string (e.g. `"april"`); contract says integer 1-12.
- `POST /dates` sends `{text}`; contract takes `{weekday, which}`.
- `POST /availability` sends `provider_id`; the contract request has no such field (provider comes from the call's selection).
