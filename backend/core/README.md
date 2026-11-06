Security update: [BOOKING-SECURITY.md](../../docs/BOOKING-SECURITY.md) supersedes
the demo identity, shared-key, console-access, storage and retention assumptions
below. Production requires scoped role credentials, human identity review,
HTTPS, a separate organization database and approved policy/storage evidence.
The old demographic verification examples apply only to synthetic development.

MemberGuide core implements the agreed `contracts/api.md`, `errors.md` and
`schema.sql`. Every record is synthetic; every appointment is simulated.

Run from the repository root with Python 3.10 or later:

```sh
# Set the same private value in the backend and Om's adapter environment.
export MEMBERGUIDE_AGENT_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

The current local service uses an ignored `.env.memberguide` with a generated
private key. To restart with that same configuration:

```sh
uv run uvicorn backend.main:app --env-file .env.memberguide --host 127.0.0.1 --port 8000
```

Synthetic startup creates `data/synthetic/memberguide.db` using the contract DDL and seeds the three
members, two plans, six providers, verbatim plan passages and ten business days
of 30-minute Eastern slots. `MEMBERGUIDE_DB_PATH` overrides the database path.
No key is invented when configuration is absent: agent requests fail closed.
Keep one Uvicorn worker; both routers belong in this one backend process.

Optional repeatable initialization (does not change the service's real clock):

```sh
uv run python -m backend.core.seed --date 2026-11-06
uv run python -m backend.core.seed --db /tmp/memberguide-demo/memberguide.db --date 2026-11-06
```

The seed uses a fixed occupancy pattern and preserves existing slots and
appointments on reruns/restarts. The documented forced weekday/time pairs move
to the next occurrence of those weekdays. Only the contract's in-person,
new-patient slot scope is generated; specialist provider records are directory
fixtures and are never bookable through these routes. Coverage dates remain
the exact 2026 fixture dates, independent of the machine clock.

Run verification without inference credits:

```sh
uv run --with httpx python -m pytest tests/core -q
uv run ruff format --check backend tests/core
uv run ruff check backend tests/core
```

`httpx` is an ephemeral test dependency for FastAPI's TestClient; this keeps the
shared project dependencies and lockfile unchanged. The suite tests the actual
router, persistence across application instances, deterministic consent rules,
write rollback, date boundaries, and simultaneous requests. CI runs these checks
on pull requests and pushes to `main`/`booking-core`. No LiveKit agent code was
changed, so these backend checks do not start an agent or consume inference.

Om's adapter can call all core routes now; OpenAPI is at `/docs`:

```sh
curl -s http://127.0.0.1:8000/calls \
  -H "X-Agent-Key: $MEMBERGUIDE_AGENT_KEY" \
  -H "X-Call-Key: $CALL_CAPABILITY" \
  -H 'Content-Type: application/json' -d '{"room":"unique-demo-room"}'
```

Generate `CALL_CAPABILITY` as a random secret of at least 32 characters before
creating a call. Include it and the service credential on every call request;
room retries require the same capability and owning service subject. The voice
adapter manages this automatically. Call IDs are never authorization.

In synthetic mode, use the returned call ID with `/calls/{id}/verify` (`4417`, birth month `4`),
then `/providers` (`primary care`, ZIP `10023`), `/select` (`P2`), `/dates`,
`/availability`, `/slot`, and `/appointment/preview`. Dates must come from the
backend clock; the fixed November 13 examples only apply to the reference demo.
Speak exactly `read_back` in code and arm only after uninterrupted playout.
Await finalized user `/turn` writes in conversation order before invoking any
tool. A post-arm turn containing exactly `yes`, `yes please`, `confirm`, or
`book it` is required by `/appointment/confirm`. Surrounding whitespace and
terminal `.`, `!`, `?` are allowed; any additional words fail closed. Server
timestamps have the contract's second precision; an answer in the same stored
second as arming is conservatively refused with `NOT_ARMED`.

The token stays in adapter code and retries reuse that token. Reconcile a lost
response with `GET /calls/{id}/appointment` or retry confirm; expiry and call
finalization do not prevent replaying a committed result. Other calls cannot
see it. Tokens and hashes are never spoken.

Siddhant's integration uses **the same `request.app.state.db` instance**:

```python
from backend.db import Database  # shared factory, not a second singleton
from backend.core.booking import appointment_view
from backend.core.common import member_view

# Inside an ops handler, get every display field from one consistent snapshot.
db = request.app.state.db
with db.snapshot() as conn:
    call = conn.execute(
        "SELECT * FROM calls ORDER BY created_at DESC, id DESC LIMIT 1"
    ).fetchone()
    # Read calls, turns, slots, drafts, appointments, events and tasks here.
    # Helpers accept this same connection; no extra connection is needed.

# Mount Siddhant's router in the shared app, so writes use ordered ingress too.
from backend.main import create_app

app = create_app(ops_router=ops_router)
```

All ops writes, including finalize, reset and take-slot, must use
`with db.transaction() as conn:`. This provides the same FIFO write barrier,
`BEGIN IMMEDIATE`, foreign keys, busy timeout, rollback and connection cleanup
as booking. A database snapshot yields `sqlite3.Row` records; don't retain a
connection after the context or use it across threads/awaits. SQL belongs in the
backend, never in the browser or voice process. No separate connection owner,
cache or booking implementation is needed.

Core stores the exact contract columns, including request version, result and
exclusion snapshots, selected provider, latest availability query and offers,
current draft, revisions, consent provenance, ordered turns and events. It
creates one complete `verification_failed` task packet when verification locks.
Expected refusals that intentionally clear state commit that transition;
unexpected errors always roll back the whole transaction. Ops must not mutate a
committed draft/token or reconstruct success from a draft.

Ops owns `/calls/latest`, follow-up/finalize, task, summary, console and admin
routes and their operator access restrictions; this change leaves
`backend/ops/`, `frontend/` and `src/` untouched. For dashboard projections,
use only the contract's allowed fields: never serialize raw rows. In particular,
redact verification answers in displayed turns, omit all tokens/detail hashes,
project expired/invalidated drafts as null, and populate confirmations only from
committed appointments. The backend cannot prove audible playout: Om still
owns the speech-interruption and pending-transcript barrier described in the
agreed contract and the [LiveKit tool documentation](https://docs.livekit.io/agents/logic/tools/definition/).
