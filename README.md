# CareLine

CareLine is a voice-assisted appointment demo. A caller can verify their identity, find a provider, hear available times and confirm a booking. The operator workspace shows conversations, follow-ups and call summaries.

**Synthetic demo:** use only the included fictional data. This project is not a production healthcare system or a claim of HIPAA compliance.

## How it works

Phone → LiveKit voice agent → booking API → operator workspace. The API checks confirmations and reserves slots atomically; competing callers cannot book the same slot.

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

See [booking security](docs/BOOKING-SECURITY.md) and [API contracts](contracts/README.md) for implementation details.
