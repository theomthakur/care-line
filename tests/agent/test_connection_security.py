import pytest

from backend_client import BackendUnavailableError, HttpBackend, make_backend
from connection_security import agent_secret


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.1:8000",
        "http://backend.example",
        "http://localhost:8000",
        "https://user:secret@backend.test",
        "https://backend.test?token=secret",
        "ftp://127.0.0.1",
    ],
)
def test_backend_refuses_insecure_or_credential_urls(url):
    with pytest.raises(ValueError):
        HttpBackend(url, "test")


def test_production_requires_tls_even_for_loopback_and_rejects_fake(monkeypatch):
    monkeypatch.setenv("MEMBERGUIDE_ENV", "production")
    with pytest.raises(ValueError):
        HttpBackend("http://127.0.0.1:8000", "test")
    monkeypatch.setenv("USE_FAKE_BACKEND", "1")
    with pytest.raises(BackendUnavailableError):
        make_backend()


def test_credential_file_requires_private_permissions(tmp_path, monkeypatch):
    path = tmp_path / "key"
    path.write_text("test-secret")
    path.chmod(0o644)
    monkeypatch.setenv("MEMBERGUIDE_AGENT_KEY_FILE", str(path))
    with pytest.raises(ValueError):
        agent_secret()
    path.chmod(0o600)
    assert agent_secret() == "test-secret"


async def test_concurrent_client_instances_never_share_call_keys(monkeypatch):
    first, second = HttpBackend(agent_key="test"), HttpBackend(agent_key="test")

    async def post_first(path, body):
        first._request_headers(path, body)
        return {"ok": True, "call_id": "call-one"}

    async def post_second(path, body):
        second._request_headers(path, body)
        return {"ok": True, "call_id": "call-two"}

    monkeypatch.setattr(first, "_post", post_first)
    monkeypatch.setattr(second, "_post", post_second)
    await first.start_call("same-room")
    await second.start_call("same-room")
    assert first._call_keys["call-one"] != second._call_keys["call-two"]
    assert second._request_headers("/calls/call-one/appointment")["X-Call-Key"] == ""
