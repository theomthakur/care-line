# Integration handoff: console + ops (Siddhant) → Aneesh, Om

Branch `feat/siddhant-console-handoff`, draft PR #1. Contracts are unchanged: `contracts/` is byte-identical to `origin/booking-core`. I touched nothing in `src/`, `backend/core/`, `data/` or `contracts/`.
Verified by mounting `ops.router` in core's `create_app` (read-only copy of `booking-core` d6722fb) and driving a real call: verify, providers, select, availability, slot, preview, armed, confirm, then `/calls/latest`, take-slot, tasks, followup, finalize, reset.

Known naming difference: core emits the event `appointment_booked`, the contract examples say `booked`. The console handles both.

## 1. Route ownership (please confirm)
| Route | Owner | Note |
| --- | --- | --- |
| `GET /calls/latest`, `GET /tasks`, `POST /tasks/{id}/complete`, `POST /admin/take-slot`, `POST /admin/reset` | **ops** | console routes, no agent key |
| `POST /calls/{id}/followup`, `POST /calls/{id}/finalize` | **ops** (proposed) | the contract lists them under "Console and handoff interfaces"; **Aneesh: don't also build them** or tell me to drop mine |
| everything else in `contracts/api.md` (`/calls`, `/turn`, `/verify`, providers, select, dates, availability, slot, preview, armed, confirm, appointment, `/now`) | **core** | ops never writes these rows |

Duplicate paths would silently shadow each other, so whoever mounts both routers should fail loudly on a duplicate.

## 2. Mounting and DB connection (verified against `origin/booking-core` d6722fb)
Core's `create_app(ops_router=...)` already exists. Mount ops with:
```python
from backend import ops

app = create_app(
    ops_router=ops.router
)  # not ops.install(): core owns the app's error handlers
```
- Ops reads `app.state.db.path` (core's `Database`) and opens its own short-lived autocommit connection with `foreign_keys=ON`. Core's `db.connect()` is not used because its connections are not thread-portable, while FastAPI runs ops dependencies and handlers on different threads. Core's POST ingress middleware already serialises every ops write.
- Ops errors are rendered inside the ops router (`OpsRoute`), so they survive core's `HTTPException` handler, which would otherwise turn `CALL_ACTIVE` / `TASK_NOT_FOUND` into `INVALID_REQUEST`.
- Agent routes (`followup`, `finalize`) use `app.state.agent_key` when the host sets it (core fails closed when empty); otherwise `AGENT_KEY` / the dev key.
- Standalone dev app: `backend/ops/dev_app.py` (unchanged).

## 3. Pending-commit hook
Not needed when mounted in core's `create_app`: its write-ingress lock serialises POSTs, so `finalize` and `/admin/reset` cannot start while a confirm is mid-commit. `summary.pending_commit` stays as an optional extra and defaults to "nothing pending". Core already writes its own `verification_failed` task on lock (`verification.py`); ops does not need to create it.

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
