"""HTTP failures must never be reported as successful actions."""

import pytest

from backend_client import BackendUnavailableError, HttpBackend


class Reply:
    status = 500

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def json(self, **_kwargs):
        return {"detail": "server error"}


class Session:
    closed = False

    def post(self, *_args, **_kwargs):
        return Reply()


async def test_http_500_cannot_become_success():
    client = HttpBackend(agent_key="test-key")
    client._session = Session()  # type: ignore[assignment]
    with pytest.raises(BackendUnavailableError):
        await client._post("/calls", {})
