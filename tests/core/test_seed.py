import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.core.seed import seed


def test_fixtures_and_repeatable_seed(db, clock):
    with db.snapshot() as conn:
        maya = conn.execute(
            "SELECT * FROM members WHERE member_digits='4417'"
        ).fetchone()
        assert maya["full_name"] == "Maya Torres"
        assert maya["birth_month"] == 4
        assert conn.execute("SELECT count(*) FROM providers").fetchone()[0] == 6
        before = [tuple(row) for row in conn.execute("SELECT * FROM slots ORDER BY id")]
    seed(db, demo_date=clock().date())
    with db.snapshot() as conn:
        assert before == [
            tuple(row) for row in conn.execute("SELECT * FROM slots ORDER BY id")
        ]
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        for slot in conn.execute("SELECT * FROM slots"):
            start = datetime.fromisoformat(slot["starts_at"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(slot["ends_at"].replace("Z", "+00:00"))
            local = start.astimezone(ZoneInfo("America/New_York"))
            assert (end - start).total_seconds() == 1800
            assert local.weekday() < 5 and 9 <= local.hour < 17
            assert local.minute in (0, 30)
        assert (
            conn.execute(
                "SELECT state FROM slots WHERE provider_id='P2' AND starts_at='2026-11-13T19:30:00Z'"
            ).fetchone()[0]
            == "open"
        )
        assert (
            conn.execute(
                "SELECT state FROM slots WHERE provider_id='P2' AND starts_at='2026-11-09T16:00:00Z'"
            ).fetchone()[0]
            == "booked"
        )


def test_schema_rejects_invalid_grid(db):
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
        conn.execute(
            "INSERT INTO slots(id,provider_id,starts_at,ends_at) VALUES ('bad','P2','2026-11-13T19:15:00Z','2026-11-13T19:45:00Z')"
        )


def test_reseed_on_monday_preserves_forced_weekdays(tmp_path, clock):
    from datetime import date

    from backend.core.db import Database

    database = Database(tmp_path / "monday.db", clock=clock)
    database.initialize()
    seed(database, demo_date=date(2026, 11, 9))
    with database.snapshot() as conn:
        assert (
            conn.execute(
                "SELECT state FROM slots WHERE provider_id='P2' AND starts_at='2026-11-12T14:30:00Z'"
            ).fetchone()[0]
            == "open"
        )
        assert (
            conn.execute(
                "SELECT state FROM slots WHERE provider_id='P2' AND starts_at='2026-11-13T19:30:00Z'"
            ).fetchone()[0]
            == "open"
        )


def test_expanded_roster_adds_providers_without_touching_the_originals(db, clock):
    from backend.core.seed import seed_expanded

    with db.snapshot() as conn:
        before = [
            tuple(r)
            for r in conn.execute(
                "SELECT * FROM slots WHERE provider_id IN ('P1','P2','P3','P4','P5','P6') ORDER BY id"
            )
        ]
    seed_expanded(db, demo_date=clock().date())
    seed_expanded(db, demo_date=clock().date())  # repeating changes nothing
    with db.snapshot() as conn:
        assert conn.execute("SELECT count(*) FROM providers").fetchone()[0] == 17
        after = [
            tuple(r)
            for r in conn.execute(
                "SELECT * FROM slots WHERE provider_id IN ('P1','P2','P3','P4','P5','P6') ORDER BY id"
            )
        ]
        assert before == after
        # Every new doctor has open times, and some are taken.
        for n in range(7, 18):
            states = {
                r[0]
                for r in conn.execute(
                    "SELECT state FROM slots WHERE provider_id=?", (f"P{n}",)
                )
            }
            assert states == {"open", "booked"}


def test_directory_route_lists_providers_and_open_times(db, clock):
    from fastapi.testclient import TestClient

    from backend.core.seed import seed_expanded
    from backend.main import create_app

    seed_expanded(db, demo_date=clock().date())
    with TestClient(create_app(database=db, agent_key="k")) as c:
        body = c.get("/providers/directory").json()
    ids = [p["id"] for p in body["providers"]]
    assert ids[:6] == ["P1", "P2", "P3", "P4", "P5", "P6"] and "P17" in ids
    haddad = next(p for p in body["providers"] if p["id"] == "P2")
    assert haddad["networks"] == ["METRO"] and haddad["open_slots"] > 0
    assert haddad["days"] and "open" in haddad["days"][0]
    reyes = next(p for p in body["providers"] if p["id"] == "P5")
    assert reyes["open_slots"] == 0 and reyes["next_open"] == []
