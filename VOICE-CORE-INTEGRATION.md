# Local voice + booking integration

This branch joins Om's voice adapter, Aneesh's SQLite booking core and Siddhant's operator routes and UI. The booking data and schedule are synthetic. No real appointments are made.

## Run locally

1. `uv sync`; in `frontend`, run `npm ci`.
2. Set up `.env.local` with `lk cloud auth` and `lk app env --write --destination .env.local`. Add `AGENT_PROFILE=mine`, `USE_FAKE_BACKEND=0`, `BACKEND_URL=http://127.0.0.1:8000`, and a unique `MEMBERGUIDE_AGENT_KEY`. Generate the latter with `python -c 'import secrets; print(secrets.token_urlsafe(32))'` and put it in `.env.local` without sharing it. Do not commit that file.
3. Stop the older `preview/server.py` before using port 8000. Start the core and handoff service: `uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000 --env-file .env.local`.
4. In `frontend`, run `npm run dev`, then open the displayed local URL. The browser does not receive the agent key.
5. Run `lk agent console` for a local microphone test. For the assigned phone number, coordinate with the team so only one production worker runs, then run `lk agent dev --deployment production` and test a real phone call.

The local operator routes are a demo, not a production authentication or multi-tenant deployment. Use fictional data only. The existing running phone demo is not automatically switched to this branch.

## Verify

`PYTHONPATH=.:src uv run pytest -q tests/core tests/ops tests/agent tests/integration`

`cd frontend && npm test -- --run && npm run build`

The adapter sends contract-shaped requests, requires the shared agent key, records finalized user turns before ordinary tool execution, and reuses the turn ID for one retry. Booking uses code-spoken backend results. On a lost confirmation response it retries the same token, then checks the call-scoped appointment; an uncertain result is never claimed as booked. Emergency instructions are delivered before waiting on the backend.

Speech-interruption timing is covered at the adapter/HTTP level using a simulated late transcript. This is not a substitute for an audio and phone interruption test using the actual LiveKit session. The operators' automatic escalation signal is not connected; do not claim it is. API rate, reliability and latency have not been established by these tests.
