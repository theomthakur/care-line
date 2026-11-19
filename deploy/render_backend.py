"""Render entry point for the fictional-data phone demo, not clinical deployment."""

import os
from pathlib import Path


def validate_demo_environment():
    if os.getenv("MEMBERGUIDE_ENV") != "synthetic":
        raise ValueError("The Render demo requires MEMBERGUIDE_ENV=synthetic")
    if len(os.getenv("MEMBERGUIDE_AGENT_KEY", "")) < 32:
        raise ValueError("The Render demo requires a strong MEMBERGUIDE_AGENT_KEY")
    path = Path(os.getenv("MEMBERGUIDE_DB_PATH", ""))
    if not path.is_absolute():
        raise ValueError("The Render demo requires an absolute MEMBERGUIDE_DB_PATH")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)


validate_demo_environment()

# Import after checking the deployment configuration; reuse all existing auth,
# verification, booking and database lifespan behavior.
from backend.main import create_app  # noqa: E402

app = create_app()


@app.get("/healthz", include_in_schema=False)
def health():
    with app.state.db.snapshot() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"status": "ok", "mode": "synthetic"}
