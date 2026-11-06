from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from fake_backend import FakeBackend


@pytest.mark.asyncio
async def test_spoken_month_and_day_is_not_treated_as_ambiguous_weekday():
    backend = FakeBackend(datetime(2026, 11, 6, tzinfo=ZoneInfo("America/New_York")))
    result = await backend.dates("unused", "Thursday November 12th")
    assert result == {"ok": True, "dates": ["2026-11-12"]}
