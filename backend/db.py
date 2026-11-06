"""Shared database API. Ops must reuse request.app.state.db, not construct an owner."""

from backend.core.db import DEFAULT_PATH, Database

__all__ = ["DEFAULT_PATH", "Database"]
