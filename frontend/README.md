# Care Line operator console

React + TypeScript + Vite. Polls `GET /calls/latest` once a second and renders **only what the backend reports**. A confirmation number appears only when `state.appointment` exists.

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, proxies /calls /tasks /admin to 127.0.0.1:8000
npm test             # vitest
npm run build        # typecheck + production build into dist/
```

Backend, in another terminal (repo root): either Aneesh's app once it exists, or the dev app with synthetic data:

```bash
CARELINE_DB=/tmp/careline-dev.db uv run uvicorn backend.ops.dev_app:app --port 8000
uv run python -m backend.ops.dev_seed --db /tmp/careline-dev.db stage armed   # unverified verified offered preview armed conflict booked finalized followup locked
```

Port 8000 is also used by `preview/server.py` on Om's branch. Run only one.
Set `CARELINE_BACKEND=http://host:port` to point the proxy elsewhere. No agent key is ever in browser code.

**Fixture mode:** `http://localhost:5173/?source=fixture` shows saved copies of `contracts/examples/state-*.json` with a stage switcher, a permanent "not a live call" banner, and all actions disabled. It never touches the network.

Everything on screen is synthetic demo data with a simulated provider schedule.
