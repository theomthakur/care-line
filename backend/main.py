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
from backend.core.seed import seed, seed_expanded
from backend.security import Authenticator, SecuritySettings

logger = logging.getLogger(__name__)


def create_app(*, database=None, agent_key=None, ops_router=None, security=None):
    security = security or SecuritySettings.from_env()
    if (
        security.environment == "production"
        and database is None
        and not os.getenv("MEMBERGUIDE_DB_PATH")
    ):
        raise ValueError("Production requires an explicit MEMBERGUIDE_DB_PATH")
    expanded = False
    if database is None:
        expanded = os.environ.get("MEMBERGUIDE_EXPANDED_ROSTER", "1") == "1"
        database = Database()
        database.one_call_per_member = (
            os.environ.get("MEMBERGUIDE_ONE_CALL_PER_MEMBER", "1") == "1"
        )
    database.environment = security.environment
    database.organization = security.organization
    database.identity_policy = security.identity_policy

    @asynccontextmanager
    async def lifespan(app):
        security.validate(database.path)
        database.initialize()
        if security.environment == "synthetic":
            seed(database)
            if expanded:
                seed_expanded(database)
        yield

    app = FastAPI(
        title="MemberGuide booking service",
        lifespan=lifespan,
        docs_url="/docs" if security.environment == "synthetic" else None,
        openapi_url="/openapi.json" if security.environment == "synthetic" else None,
        redoc_url=None,
    )
    app.state.db = database
    app.state.db_path = database.path
    app.state.write_ingress = asyncio.Lock()
    # Fail closed if configuration is missing. Never invent or log a fallback key.
    app.state.agent_key = (
        agent_key
        if agent_key is not None
        else os.environ.get("MEMBERGUIDE_AGENT_KEY", "")
    )
    app.state.security = security
    app.state.auth = Authenticator(security, app.state.agent_key)

    @app.middleware("http")
    async def ordered_write_ingress(request: Request, call_next):
        async def respond():
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response

        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return await respond()
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
            return await respond()
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
        from backend.ops.errors import envelope

        return envelope(exc)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        # No request body, SQL values, credentials or tokens in client/log output.
        logger.error("MemberGuide request failed (%s)", type(exc).__name__)
        error = DomainError("INTERNAL_ERROR")
        return JSONResponse(error.body, status_code=error.status)

    app.include_router(router)
    from backend.identity import router as identity_router

    app.include_router(identity_router)
    if ops_router is None:
        from backend.ops.router import router as ops_router
    app.include_router(ops_router)
    return app


app = create_app()
