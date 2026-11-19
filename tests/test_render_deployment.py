"""Exercise the hosted configuration against the real booking/auth boundary."""

import importlib

import pytest
from fastapi.testclient import TestClient

from deploy.render_agent import configure_backend


@pytest.fixture
def demo_env(monkeypatch, tmp_path):
    values = {
        "MEMBERGUIDE_ENV": "synthetic",
        "MEMBERGUIDE_AGENT_KEY": "synthetic-test-key-at-least-32-characters",
        "MEMBERGUIDE_DB_PATH": str(tmp_path / "persistent" / "demo.db"),
        "BOOKING_API_HOST": "careline-example.onrender.com",
        "LIVEKIT_URL": "wss://example.livekit.cloud",
        "LIVEKIT_API_KEY": "synthetic-test",
        "LIVEKIT_API_SECRET": "synthetic-test",
        "BACKEND_URL": "http://127.0.0.1:8001",
        "AGENT_PROFILE": "booking",
        "USE_FAKE_BACKEND": "1",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    for key in ("MEMBERGUIDE_CREDENTIALS_FILE", "MEMBERGUIDE_AGENT_KEY_FILE"):
        monkeypatch.delenv(key, raising=False)
    return values


def test_worker_configuration_uses_https_and_real_backend(demo_env, monkeypatch):
    monkeypatch.setenv("USE_FAKE_BACKEND", "1")
    configure_backend()
    import os

    assert os.environ["BACKEND_URL"] == "https://careline-example.onrender.com"
    assert os.environ["USE_FAKE_BACKEND"] == "0"
    assert os.environ["AGENT_PROFILE"] == "mine"


@pytest.mark.parametrize(
    "host",
    [
        "",
        "http://example.com",
        "user@example.com",
        "example.com/path",
        "example.com:80",
    ],
)
def test_worker_rejects_invalid_hosts(demo_env, monkeypatch, host):
    monkeypatch.setenv("BOOKING_API_HOST", host)
    with pytest.raises(ValueError):
        configure_backend()


def test_worker_rejects_missing_credentials(demo_env, monkeypatch):
    monkeypatch.delenv("LIVEKIT_API_SECRET")
    with pytest.raises(ValueError, match="LIVEKIT_API_SECRET"):
        configure_backend()


def test_hosted_backend_health_auth_verification_and_restart(demo_env):
    module = importlib.import_module("deploy.render_backend")
    module = importlib.reload(module)
    with TestClient(module.app, base_url="https://demo.test") as client:
        assert client.get("/healthz").json() == {"status": "ok", "mode": "synthetic"}
        assert client.post("/calls", json={"room": "render-test"}).status_code == 401
        client.headers.update(
            {
                "X-Agent-Key": demo_env["MEMBERGUIDE_AGENT_KEY"],
                "X-Call-Key": "synthetic-call-key-at-least-32-characters",
            }
        )
        response = client.post("/calls", json={"room": "render-test"})
        assert response.status_code == 201
        call_id = response.json()["call_id"]
        response = client.post(
            f"/calls/{call_id}/verify", json={"member_digits": "4417", "birth_month": 4}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "verified"
    # A new app/DB connection over the same disk must retain the call.
    module = importlib.reload(module)
    with (
        TestClient(module.app, base_url="https://demo.test"),
        module.app.state.db.snapshot() as conn,
    ):
        assert conn.execute("SELECT id FROM calls WHERE id=?", (call_id,)).fetchone()


def test_backend_launcher_rejects_non_demo(demo_env, monkeypatch):
    module = importlib.import_module("deploy.render_backend")
    monkeypatch.setenv("MEMBERGUIDE_ENV", "production")
    with pytest.raises(ValueError, match="synthetic"):
        module.validate_demo_environment()
