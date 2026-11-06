# Local integrated demo

This is a synthetic, single-process bridge for the voice agent and operator screen while the team's backend and UI are being integrated. It is not a production service: data is in memory, resets on restart, and is not connected to a real insurer, medical scheduling system, or SMS service. Use fictional data only.

1. Run `uv sync`.
2. Link LiveKit and create credentials with `lk cloud auth` and `lk app env --write --destination .env.local`.
3. Add `AGENT_PROFILE=mine`, `BACKEND_URL=http://127.0.0.1:8000`, and `USE_FAKE_BACKEND=0` to `.env.local`.
4. In one terminal run `uv run python preview/server.py` and open http://127.0.0.1:8000.
5. In another terminal run `lk agent console` for a local microphone test. To use a real phone, rent a number, configure the dispatch rule, and run `lk agent dev --deployment production`; use only one worker per LiveKit project.

Test member: last four digits `4417`, birth month `April`, ZIP `10019`. This is invented data. The dashboard refreshes during a call. The booking is a simulation and requires a clear confirmation after the read-back.

The dashboard's **Load sample call** and **Reset preview** buttons reset the in-memory demo. Don't press them during a live demo call. The agent and server use the development-only key `dev-agent-key`; this local preview must not be exposed publicly.
