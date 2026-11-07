# CareLine

CareLine is a voice-assisted member support prototype built for the Take2 voice agent hackathon. It helps a caller find an eligible primary care provider and book an appointment by phone. A companion workspace gives support staff the conversation and context needed to follow up.

Finding care can involve long hold times, navigating provider directories and repeating information. CareLine explores a more direct path: a voice agent talks with the member, calls a booking service for verified information and keeps the operator informed.

**[Open the hosted UI preview](https://careline-member-guide.vercel.app/)**

**Synthetic demo:** use only the included fictional data. This project is not a production healthcare system or a claim of HIPAA compliance.

## How it works

1. A member calls the configured phone number and speaks with the LiveKit voice agent.
2. The booking API checks synthetic member details, searches eligible providers and returns open slots.
3. The agent reads the chosen slot back. The backend requires a fresh confirmation before booking.
4. The appointment is saved atomically: if callers compete for one slot, only one booking succeeds and the others must choose another time.
5. The workspace displays call status, conversation, appointment and follow-up information for an operator.

The voice layer uses **LiveKit and Python**; the booking service uses **FastAPI and SQLite**; the workspace uses **React and TypeScript**. The hosted Vercel preview uses saved examples and is separate from the live phone service.

## Workspace

- **Overview and conversations:** find calls and inspect their progress and transcript.
- **Follow-ups and providers:** see handoff context and provider information.
- **Explore:** open the system design and presentation.
- **Appearance:** switch between light and dark from the sidebar; Settings also offers a system theme. Developer view is available directly in the sidebar.

The live agent, backend and workspace are separate processes. The Vercel preview does not connect to a phone number or create bookings.

## Run locally

Requirements: Python and `uv`, Node.js, and a LiveKit project for phone calls.

```bash
uv sync
cd frontend && npm ci && cd ..
cp .env.example .env.local
```

Add your LiveKit credentials to `.env.local`. Create separate local service credentials:

```bash
mkdir -p secrets && chmod 700 secrets
for role in agent operator admin; do
  uv run python -m backend.credentials --registry secrets/registry.json --token-file "secrets/$role.key" --subject "$role" --organization synthetic --role "$role"
done
```

Set these values in `.env.local`, replacing `<project>` with the absolute project path:

```text
AGENT_PROFILE=mine
BACKEND_URL=http://127.0.0.1:8001
MEMBERGUIDE_CREDENTIALS_FILE=<project>/secrets/registry.json
MEMBERGUIDE_AGENT_KEY_FILE=<project>/secrets/agent.key
MEMBERGUIDE_OPERATOR_KEY_FILE=<project>/secrets/operator.key
MEMBERGUIDE_ADMIN_KEY_FILE=<project>/secrets/admin.key
```

Run the API and workspace in separate terminals:

```bash
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8001 --env-file .env.local
```

```bash
cd frontend
MEMBERGUIDE_OPERATOR_KEY_FILE=../secrets/operator.key MEMBERGUIDE_ADMIN_KEY_FILE=../secrets/admin.key CARELINE_BACKEND=http://127.0.0.1:8001 npm run dev
```

Open the URL printed by Vite. To run the voice agent with your configured LiveKit project and dispatch rule, run `lk agent dev --no-reload --deployment production` from the project root.

## Check

```bash
uv run python -m pytest -q
cd frontend && npm test && npm run build
```

The Vercel build is a **read-only synthetic UI preview**. A live phone experience also needs a running backend and LiveKit agent; Vercel alone does not provide those services.

The optional live identity CI scenario runs only when `LIVEKIT_IDENTITY_TEST_ENABLED` is set to `true` and dedicated synthetic LiveKit test credentials are configured. A skipped scenario has not been verified.

See [booking security](docs/BOOKING-SECURITY.md) and [API contracts](contracts/README.md) for implementation details.
