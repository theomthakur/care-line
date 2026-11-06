# contracts/

Locked at 4:00 PM by Om, Aneesh and Siddhant, before any coding agent starts.
Put here: `api.md` (routes, from plan section 8), `errors.md`, `schema.sql`, and `examples/` (sample responses and `state-*.json`).
Nobody changes a contract alone. Say it out loud, agree it, update this folder on `main`, and everyone rebases.

## Security contract update

[BOOKING-SECURITY.md](../docs/BOOKING-SECURITY.md) supersedes demo authentication,
verification and unauthenticated console assumptions in this directory. Network
calls require scoped service roles and a separate call capability; production
verification requires human review. The base DDL is extended through the additive
`backend/security_schema.sql` migration. Organizations/environments use separate,
durably labelled databases. Demographic examples remain synthetic-only fixtures.
