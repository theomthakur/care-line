"""Run locally: uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000."""

import asyncio
import logging
import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend.core.db import Database
from backend.core.errors import DomainError
from backend.core.routes import router
from backend.core.seed import seed

logger = logging.getLogger(__name__)


def create_app(*, database=None, agent_key=None, ops_router=None):
    database = database or Database()

    @asynccontextmanager
    async def lifespan(app):
        database.initialize()
        seed(database)
        yield

    app = FastAPI(title="MemberGuide synthetic booking service", lifespan=lifespan)
    app.state.db = database
    app.state.write_ingress = asyncio.Lock()
    # Fail closed if configuration is missing. Never invent or log a fallback key.
    app.state.agent_key = (
        agent_key
        if agent_key is not None
        else os.environ.get("MEMBERGUIDE_AGENT_KEY", "")
    )

    @app.middleware("http")
    async def ordered_write_ingress(request: Request, call_next):
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return await call_next(request)
        # Queue before request-body parsing and thread-pool dispatch. A finalized
        # user turn already admitted here cannot be overtaken by confirm/reset.
        # Ops routes mounted on this app participate in the same barrier.
        try:
            await asyncio.wait_for(
                app.state.write_ingress.acquire(), timeout=database.timeout
            )
        except asyncio.TimeoutError:
            error = DomainError("SERVICE_UNAVAILABLE")
            return JSONResponse(error.body, status_code=error.status)
        try:
            return await call_next(request)
        finally:
            app.state.write_ingress.release()

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return JSONResponse(exc.body, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        error = DomainError("INVALID_REQUEST")
        return JSONResponse(error.body, status_code=error.status)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request: Request, exc: sqlite3.OperationalError):
        logger.error("MemberGuide SQLite operation failed (%s)", type(exc).__name__)
        error = DomainError("SERVICE_UNAVAILABLE")
        return JSONResponse(error.body, status_code=error.status)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        error = DomainError("INVALID_REQUEST")
        return JSONResponse(error.body, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        # No request body, SQL values, credentials or tokens in client/log output.
        logger.error("MemberGuide request failed (%s)", type(exc).__name__)
        error = DomainError("INTERNAL_ERROR")
        return JSONResponse(error.body, status_code=error.status)

    app.include_router(router)
    if ops_router is not None:
        app.include_router(ops_router)
    return app


app = create_app()
