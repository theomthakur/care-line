# Booking backend security and operations

`booking-core-compliance` includes `om/workspace-and-call-fixes`. This document
supersedes the demo transport and identity assumptions in `contracts/api.md`.
Appointments still use the project's simulated scheduling backend.

The implementation supplies access controls and maintenance tooling. It does
not establish regulatory compliance, approve an identity procedure, provision
an encrypted cloud volume, rotate an existing production secret, or approve a
retention schedule. No approved identity/retention policy was found on the
workspace-and-call-fixes branch. Production startup fails until the required
organization, policy references, and current storage/recovery evidence exist.

## Identity

Production has no demographic matching endpoint. `POST /calls/{id}/verify {}`
checks a prior human review. Without one, it returns
`HUMAN_VERIFICATION_REQUIRED` and atomically creates one `verification_failed`
task. The caller hears that member services must verify identity through the
approved process; the agent cannot transfer the call or complete that review.
The production tool has no identity-answer arguments. User/assistant turns
before verification store `[identity pending]`, and follow-up details use a
generic description. SDK/LiveKit transcripts are a separate data store and must
have their own approved collection and retention configuration.

An individually attributable `identity_reviewer` credential may submit:

```http
POST /identity/calls/{call_id}/review
Authorization: Bearer <reviewer credential>
Content-Type: application/json

{"policy":"<configured reviewed policy version>","reference":"<external_case_id>","outcome":"verified","member_id":"<internal patient ID>"}
```

A failed review uses `outcome: "failed"` and omits `member_id`. Three failed
reviews permanently lock that call and leave a human task. Reference retries
are idempotent; conflicting results, reassigning a verified patient, and
unlocking a locked call are refused. Review provenance records the authenticated
reviewer, policy version, case reference, outcome, and time. Raw documents,
codes, or answers belong in the approved review system, not this request.

Before enabling production, the identity owner must review the accepted
methods, independent contact channel, reviewer authentication/MFA, evidence
requirements, retry/recovery procedure, and authorized-representative policy.
Provision a separate credential for each reviewer or an identity gateway that
preserves individual attribution. An LLM or the voice service must never hold
a reviewer credential. Last-four/month matching is available only against the
separate synthetic database for existing demo scenarios.

## Access boundaries and transport

Each backend deployment, database, credential registry, and archive belongs to
one organization and environment. `deployment_scope` is immutable across
restarts. The service refuses an organization/environment mismatch and refuses
to relabel a legacy database as production. Provision a fresh production DB and
import patients through an independently reviewed ingestion path. There is no
request-selectable database or organization.

All core routes require an `agent` credential. Console/history/state/directory
and task routes require `operator`; demo admin actions require `admin` and are
disabled in production. Review routes require `identity_reviewer`. Production
does not accept the legacy shared-key fallback.

Agents generate a random `X-Call-Key` before `POST /calls` and retain it for
retries and that call's subsequent requests. The database stores its hash and
the owning service subject. Every call operation checks both, including turn
writes, verification, finalization, follow-up, and appointment reconciliation.
Unknown and inaccessible calls return the same refusal before body validation.
Knowing a room, call ID, patient ID, or booking token grants no access. Booking
transactions also enforce the verified call's patient and draft/token ownership.
Existing calls without a capability remain visible to authorized operators but
cannot be resumed by agents. Workers must retain their in-memory capability;
a replacement phone session starts a new room/call.

Cross-network traffic requires HTTPS with certificate and hostname verification.
The agent refuses remote HTTP and credential-bearing URLs and never follows
redirects. Synthetic HTTP is limited to literal loopback addresses. The backend
checks its ASGI scheme, and `deploy/memberguide.service` serves TLS directly with
forwarded headers disabled. Restrict inbound TCP 8443 to the voice workers and
authorized operator/reviewer gateway. Never expose the DB file or a database
port. A proxy deployment must explicitly trust only its own TLS ingress.

The local Vite console binds to loopback. Set its server-side
`MEMBERGUIDE_OPERATOR_KEY_FILE` and `MEMBERGUIDE_ADMIN_KEY_FILE`; its proxy strips
incoming credentials and injects the appropriate role from an owner-only file.
No service credentials enter browser code or localStorage. Production console
hosting requires an authenticated operator gateway with the same role boundary.

## Credentials and environment separation

Run this on the credential-management host, outside the repository, for each
needed subject and role:

```sh
uv run python -m backend.credentials \
  --registry /secure/memberguide/service-credentials.json \
  --token-file /secure/memberguide/voice.secret \
  --subject voice-workers --organization YOUR_ORG --role agent
```

Use distinct output files for operator/reviewer/admin credentials. Store and
distribute them through the deployment secret manager. The registry contains
SHA-256 digests, subjects, organizations, roles and validity windows. Secret
files must be regular files with owner-only permissions. The command never
prints tokens. Rotate from a single credential-management process; it publishes
the new registry before the new token, retaining at most one hour of overlap.
Remove a registry entry to revoke it immediately. The backend reloads the
registry and the adapter reloads its token file on every request. Stable subjects
preserve active calls across rotation; changing a subject removes that access.
Rotate any existing service keys through this process before production rollout.

Required production backend configuration:

```dotenv
MEMBERGUIDE_ENV=production
MEMBERGUIDE_ORGANIZATION=YOUR_ORG
MEMBERGUIDE_DB_PATH=/srv/memberguide/database/memberguide.db
MEMBERGUIDE_CREDENTIALS_FILE=/etc/memberguide/service-credentials.json
MEMBERGUIDE_IDENTITY_POLICY=YOUR_REVIEWED_POLICY_VERSION
MEMBERGUIDE_RETENTION_POLICY_FILE=/etc/memberguide/retention.json
MEMBERGUIDE_STORAGE_EVIDENCE_FILE=/etc/memberguide/storage-evidence.json
MEMBERGUIDE_BIND_ADDRESS=YOUR_PRIVATE_INTERFACE_ADDRESS
```

The voice worker uses `MEMBERGUIDE_ENV=production`,
`MEMBERGUIDE_AGENT_KEY_FILE=<secret mount>`, `USE_FAKE_BACKEND=0`,
`AGENT_PROFILE=mine`, and an HTTPS `BACKEND_URL`. Use a trusted public certificate
or an organization CA bundle; never disable verification. Keep development and
production in separate LiveKit projects, runtime accounts, secrets, volumes and
backup locations, consistent with the [LiveKit deployment guidance](https://docs.livekit.io/deploy/custom/deployments/).
The default development DB moved to `data/synthetic/memberguide.db`; old demo
files are not automatically imported. Seed/fake/dev entrypoints refuse
production, and database artifacts/secrets are excluded from Git and images.

## Storage, retention, deletion and recovery

Provision an encrypted filesystem/managed volume for `/srv/memberguide`,
including database pages, WAL/SHM files, swap/crash handling, recovery targets and
maintenance files. Restrict it to the backend service account; the DB directory
must be mode 0700 and files 0600. The service uses secure deletion on connections
and checkpoints the WAL after retention. Encryption at rest is supplied by the
deployment storage layer; SQLite alone neither supplies it nor decides compliance.

Fill in `deploy/storage-evidence.example.json` with reviewed volume/access,
encrypted off-host backup, and successful recovery-test references and a review
expiry. The DB path must fall under that reviewed directory. This is operator
evidence, not a cryptographic measurement of the storage platform. Complete
`deploy/retention.example.json` with actual approved values; its empty defaults
intentionally fail validation. Do not copy test-fixture approvals into production.

Retention periods are separate for raw turns, call envelopes/review provenance,
appointments, summaries, tasks, and backups. Calls must outlive dependent records;
backups must expire within the shortest record period. Raw turn text expires
independently, including for live calls. Consent sequence/timestamp rows remain
until appointment dependencies expire; expired text becomes `[expired]`. Closed
call request snapshots and draft readbacks are scrubbed too. Appointment retention
starts at the visit end; summary/call retention starts at finalization. Abandoned
calls finalize after the approved call inactivity period. Legal holds block
record deletion and must be handled in the approved policy.

Create an owner-only backup-key JSON file containing a Fernet key list, newest
first, using the secret manager. Keep keys separate from archives. Retain old
decryption keys until their backups expire. Initialize the current erasure ledger
once, before enabling the timer:

```sh
uv run python -m backend.lifecycle init-ledger \
  --policy /etc/memberguide/retention.json \
  --archive /srv/memberguide/backups \
  --keys /etc/memberguide/backup-keys.json \
  --ledger /srv/memberguide/erasure-ledger/current.enc
```

With the same options, `backup` applies retention, takes a consistent SQLite
snapshot, encrypts/authenticates it, and expires old archives using their
authenticated creation time. Enable the supplied hourly systemd timer and alert
on failures; upload the encrypted archives to the reviewed restricted off-host
vault over TLS and enforce the same expiry on **all versions and replicas**.
The local tool cannot expire an unconfigured external vault. Keep the current
encrypted erasure ledger durably replicated separately from historical backups.

`erase --member INTERNAL_ID --reference APPROVED_CASE_ID` records a durable
tombstone before deleting that patient's calls, turns, appointments, summaries,
tasks, reviews, grants, and member record. Resolve live calls and legal holds
first. IDs must never be reused. Older encrypted archives may contain the record
until their approved expiry; recovery requires the current ledger and replays
every deletion before the restored database can be served.

`recover --backup FILE --target NEW_DB_PATH` refuses overwrite, expired archives,
wrong scopes, missing ledgers, wrong keys and tampered ciphertext. It verifies
SQLite integrity and foreign keys, then applies deletions and current retention.
Run it regularly into a fresh isolated directory on the encrypted volume, verify
expected appointments and deletions, record elapsed time/RPO/RTO and reviewer
evidence, then remove the recovery copy. The code has automated recovery tests;
the deployment owner must perform and document the real vault recovery drill.
Snapshots currently use memory proportional to the database; review capacity
before moving beyond this prototype.

## Validation

```sh
uv sync --locked
uv run python -m pytest tests/core tests/ops tests/agent tests/integration -q
uv run ruff format --check backend tests/core tests/ops tests/agent tests/integration tests/security_helpers.py src/backend_client.py src/connection_security.py src/my_agent.py src/flow.py scripts
uv run ruff check backend tests/core tests/ops tests/agent tests/integration tests/security_helpers.py src/backend_client.py src/connection_security.py src/my_agent.py src/flow.py scripts
```

The suite covers every unauthorized route, cross-organization/role/subject access,
cross-patient capabilities, concurrent calls, credential expiry/revocation/rotation,
human-review lockout/idempotency, plaintext rejection, synthetic separation,
retention/holds, encrypted recovery, and deletion replay. A real text-debugger
conversation tested the production status tool and refusal to bypass review.
The committed single scenario passed against an isolated TLS fixture.

CI runs backend/adapter checks on PRs and pushes. The single identity scenario
also runs on every push to main, with concurrency one. Configure
`LIVEKIT_TEST_URL`, `LIVEKIT_TEST_API_KEY`, and `LIVEKIT_TEST_API_SECRET` as CI
secrets for a synthetic test project; absent credentials fail that job explicitly.
`scripts/identity_test_backend.py` creates test-only policies and temporary TLS
trust, contains no patients, and is never a production deployment command.
