"""Ops side of Care Line: console read model, handoff packets, summaries, admin.

Mount with ``backend.ops.install(app)`` (adds the router and the contract error envelope). This package reads the
rows the core routes write (contracts/schema.sql) and never makes a booking decision.
"""

from .router import install, router

__all__ = ["install", "router"]
