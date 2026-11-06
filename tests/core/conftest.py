from datetime import datetime, timedelta, timezone

import pytest

from backend.core.db import Database
from backend.core.seed import seed


class Clock:
    def __init__(self):
        self.value = datetime(2026, 11, 6, 21, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds=1):
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def db(tmp_path, clock):
    database = Database(tmp_path / "memberguide.db", clock=clock)
    database.initialize()
    seed(database, demo_date=clock().date())
    return database


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from backend.main import create_app

    with TestClient(create_app(database=db, agent_key="core-test-key")) as test_client:
        test_client.headers["X-Agent-Key"] = "core-test-key"
        yield test_client
