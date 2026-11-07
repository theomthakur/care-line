"""Background closer for calls that never hung up cleanly.

The voice agent finalizes a call from its shutdown hook. When that hook never runs (worker
killed, line dropped) the call would stay ``live`` forever with no summary. This task closes such
calls after ``CARELINE_ABANDON_AFTER_S`` of silence (``summary.ABANDON_AFTER``).

Design rules:
- It is a background task, never a GET handler: reading the console writes nothing.
- It joins core's write barrier (``app.state.write_ingress``) when the host has one, so a close
  can never interleave with a request core has already admitted.
- Every close is conditional and atomic inside one write transaction (``finalize_call
  (idle_before=...)``), so any turn or event that lands first keeps the call live.
- It owns its own SQLite connection and never raises: a failed pass is logged and retried.

Core does not need to change: the first request to an ops route starts the task on the running
event loop (``ensure_sweeper``). A host that has a lifespan can instead call ``run_sweeper``.
"""

from __future__ import annotations

import asyncio
import logging
import os

from fastapi import FastAPI

from .db import open_conn
from .summary import close_abandoned

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_S = float(os.getenv("CARELINE_SWEEP_INTERVAL_S", "15"))


def sweep_once(app: FastAPI) -> list[str]:
    """One pass on a private connection. Returns the ids of the calls it closed."""
    conn = open_conn(app.state)
    try:
        return close_abandoned(conn)
    finally:
        conn.close()


async def run_sweeper(app: FastAPI, interval: float | None = None) -> None:
    every = SWEEP_INTERVAL_S if interval is None else interval
    if every <= 0:  # disabled
        return
    while True:
        await asyncio.sleep(every)
        try:
            barrier = getattr(app.state, "write_ingress", None)
            if barrier is not None:
                async with barrier:
                    closed = await asyncio.to_thread(sweep_once, app)
            else:
                closed = await asyncio.to_thread(sweep_once, app)
            if closed:
                logger.info("closed %d call(s) that never hung up cleanly", len(closed))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # keep sweeping; never take the app down
            logger.warning("abandoned-call sweep failed (%s)", type(exc).__name__)


def ensure_sweeper(app: FastAPI) -> None:
    """Start the sweeper task once for this app, on the running event loop."""
    task = getattr(app.state, "ops_sweeper", None)
    if task is not None and not task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if SWEEP_INTERVAL_S > 0:
        app.state.ops_sweeper = loop.create_task(run_sweeper(app))
