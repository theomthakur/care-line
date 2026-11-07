"""Explicit synthetic credentials for backend boundary tests."""

import json
from dataclasses import replace

from backend.credentials import write_private
from backend.security import Authenticator, SecuritySettings, digest

TOKENS = {
    role: f"synthetic-{role}-credential-at-least-32-characters"
    for role in ("operator", "admin", "identity_reviewer")
}


def configure_roles(app, path, agent_key="dev-agent-key"):
    settings = getattr(app.state, "security", SecuritySettings())
    records = [
        {
            "subject": "development-agent",
            "organization": settings.organization,
            "role": "agent",
            "sha256": digest(agent_key),
            "not_before": "2020-01-01T00:00:00Z",
            "expires_at": "2099-01-01T00:00:00Z",
        }
    ]
    records += [
        {**records[0], "subject": role, "role": role, "sha256": digest(token)}
        for role, token in TOKENS.items()
    ]
    write_private(path, json.dumps(records))
    settings = replace(settings, credentials_file=str(path))
    app.state.security = settings
    app.state.auth = Authenticator(settings)
    return settings
