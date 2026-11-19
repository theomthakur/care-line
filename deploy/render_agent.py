"""Run the existing voice agent against the Render HTTPS booking endpoint."""

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit


def configure_backend():
    if os.getenv("MEMBERGUIDE_ENV") != "synthetic":
        raise ValueError("The Render demo requires MEMBERGUIDE_ENV=synthetic")
    if len(os.getenv("MEMBERGUIDE_AGENT_KEY", "")) < 32:
        raise ValueError("The Render demo requires a strong MEMBERGUIDE_AGENT_KEY")
    for key in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        if not os.getenv(key):
            raise ValueError(f"Missing required environment variable: {key}")
    host = os.getenv("BOOKING_API_HOST", "")
    parsed = urlsplit("https://" + host)
    if not host or parsed.hostname != host or parsed.port or parsed.path:
        raise ValueError("BOOKING_API_HOST must be a bare HTTPS hostname")
    os.environ["BACKEND_URL"] = "https://" + host
    os.environ["USE_FAKE_BACKEND"] = "0"
    os.environ["AGENT_PROFILE"] = "mine"


def main():
    configure_backend()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from agent import cli, server

    cli.run_app(server)


if __name__ == "__main__":
    main()
