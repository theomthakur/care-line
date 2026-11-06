"""Transport and secret-file checks shared by the voice adapter configuration."""

import ipaddress
import os
import stat
from pathlib import Path
from urllib.parse import urlsplit


def validate_backend_url(url):
    parsed = urlsplit(url)
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.hostname
    ):
        raise ValueError("Backend URL must not contain credentials, query or fragment")
    if parsed.scheme == "https":
        return
    try:
        local = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        local = False
    if not (
        parsed.scheme == "http"
        and local
        and os.getenv("MEMBERGUIDE_ENV", "synthetic") == "synthetic"
    ):
        raise ValueError(
            "Backend requires HTTPS; HTTP is allowed only for synthetic loopback development"
        )


def agent_secret():
    filename = os.getenv("MEMBERGUIDE_AGENT_KEY_FILE")
    if filename:
        path = Path(filename)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError("Agent credential must be an owner-only regular file")
        return path.read_text().strip()
    return os.getenv("MEMBERGUIDE_AGENT_KEY", "")
