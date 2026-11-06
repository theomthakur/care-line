"""Business clock. The backend is the only clock; tests replace ``now``."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def now() -> datetime:
    return datetime.now(timezone.utc)


def utc_str(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def spoken(iso: str) -> str:
    """'Friday, November 13, 2026 at 3:00 PM Eastern time' (matches contracts/examples)."""
    d = parse_utc(iso).astimezone(ET)
    hour = d.hour % 12 or 12
    return (
        f"{d.strftime('%A, %B')} {d.day}, {d.year} at {hour}:{d.minute:02d} "
        f"{'AM' if d.hour < 12 else 'PM'} Eastern time"
    )
