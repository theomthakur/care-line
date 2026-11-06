"""DEV ONLY standalone app so the console can run before the core backend exists.

    uv run python -m backend.ops.dev_seed --db /tmp/careline.db init
    CARELINE_DB=/tmp/careline.db uv run uvicorn backend.ops.dev_app:app --port 8000

If the database file is missing it is created with synthetic fixtures. Aneesh's real app
mounts ``backend.ops.install(app)`` instead and uses his own database.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from . import install
from .dev_seed import init_db

DB_PATH = Path(os.getenv("CARELINE_DB", "/tmp/careline-dev.db"))
if not DB_PATH.exists():
    init_db(DB_PATH).close()

app = FastAPI(title="Care Line ops (dev)")
app.state.db_path = DB_PATH
install(app)
