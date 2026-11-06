"""Repeatable synthetic section 9 fixtures. Existing rows/bookings are preserved."""

import argparse
from datetime import date, datetime, time, timedelta

from .common import EASTERN, utc
from .db import Database

PROVIDERS = [
    ("P1", "Dr. Lena Park", "primary care", "10019", "212-555-0101", 0, ["METRO"]),
    ("P2", "Dr. Omar Haddad", "primary care", "10023", "212-555-0102", 1, ["METRO"]),
    ("P3", "Dr. Grace Liu", "primary care", "10019", "212-555-0103", 1, ["VALUE"]),
    (
        "P4",
        "Westside Family Medicine",
        "primary care",
        "10024",
        "212-555-0104",
        1,
        ["METRO", "VALUE"],
    ),
    ("P5", "Dr. Samuel Reyes", "dermatology", "10019", "212-555-0105", 1, ["METRO"]),
    ("P6", "Dr. Nina Rao", "cardiology", "10023", "212-555-0106", 1, ["VALUE"]),
]
GOLD_PREV = "One annual preventive visit with an in-network primary care provider is covered at no cost share when billed as preventive. Other services during the visit may be billed separately."
BASIC_PREV = "One annual preventive visit with an in-network primary care provider is covered when billed as preventive. Other services may be billed separately."


def seed(db, *, demo_date=None):
    demo_date = demo_date or db.now().astimezone(EASTERN).date()
    # Keep the promised weekday/time pairs even when reseeded on another day.
    next_days = {
        weekday: demo_date + timedelta(days=(weekday - demo_date.weekday()) % 7 or 7)
        for weekday in range(5)
    }
    forced = {
        ("P2", next_days[3]): {(9, 30), (10, 30)},
        ("P2", next_days[4]): {
            (14, 30),
            (15, 0),
            (16, 0),
        },
        ("P1", next_days[3]): {(10, 0)},
        ("P4", next_days[2]): {(13, 0)},
        ("P6", next_days[1]): {(11, 0)},
        ("P6", next_days[2]): {(14, 0)},
    }
    with db.transaction() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO plans VALUES (?,?,?)",
            [("GOLD", "Gold 2026", "METRO"), ("BASIC", "Basic 2026", "VALUE")],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO members VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    "M1",
                    "Maya Torres",
                    "Maya T.",
                    "4417",
                    4,
                    "GOLD",
                    "2026-01-01",
                    "2026-12-31",
                ),
                (
                    "M2",
                    "Riley Chen",
                    "Riley C.",
                    "2261",
                    6,
                    "BASIC",
                    "2026-01-01",
                    "2026-12-31",
                ),
                (
                    "M3",
                    "Devon Clarke",
                    "Devon C.",
                    "8832",
                    9,
                    "BASIC",
                    "2026-01-01",
                    "2026-10-31",
                ),
            ],
        )
        for plan in ("GOLD", "BASIC"):
            for suffix, topic, title, text in [
                (
                    "PREV",
                    "preventive",
                    "Preventive care",
                    GOLD_PREV if plan == "GOLD" else BASIC_PREV,
                ),
                (
                    "REF",
                    "referral",
                    "Referrals",
                    "Gold members do not need a referral to see an in-network specialist."
                    if plan == "GOLD"
                    else "Basic members need a referral from their primary care provider before seeing a specialist.",
                ),
                (
                    "CHG",
                    "plan_change",
                    "Plan changes",
                    "Plan changes are handled by a member services representative during open enrollment or after a qualifying life event.",
                ),
            ]:
                conn.execute(
                    "INSERT OR IGNORE INTO plan_sections VALUES (?,?,?,?,?)",
                    (f"{plan}-{suffix}", plan, topic, title, text),
                )
        for *provider, networks in PROVIDERS:
            conn.execute(
                "INSERT OR IGNORE INTO providers VALUES (?,?,?,?,?,?)", provider
            )
            conn.executemany(
                "INSERT OR IGNORE INTO provider_networks VALUES (?,?)",
                [(provider[0], network) for network in networks],
            )
        days = []
        day = demo_date
        while len(days) < 10:
            if day.weekday() < 5:
                days.append(day)
            day += timedelta(days=1)
        for provider_index, provider in enumerate(PROVIDERS):
            pid = provider[0]
            for day_index, day in enumerate(days):
                for cell in range(16):
                    hour, minute = 9 + cell // 2, (cell % 2) * 30
                    occupied = (
                        cell + day_index + provider_index
                    ) % 5 < 2 or pid == "P5"
                    if (pid, day) in forced:
                        occupied = (hour, minute) not in forced[(pid, day)]
                    if (
                        pid == "P2"
                        and day == next_days[0]
                        and (hour, minute) == (11, 0)
                    ):
                        occupied = True
                    if pid == "P1" and day == next_days[4] and hour >= 14:
                        occupied = True
                    start = datetime.combine(day, time(hour, minute), tzinfo=EASTERN)
                    state = "booked" if occupied else "open"
                    conn.execute(
                        "INSERT OR IGNORE INTO slots(id,provider_id,starts_at,ends_at,state,occupancy_reason,seed_state) VALUES (?,?,?,?,?,?,?)",
                        (
                            f"S-{pid}-{day:%Y%m%d}-{hour:02}{minute:02}",
                            pid,
                            utc(start),
                            utc(start + timedelta(minutes=30)),
                            state,
                            "seeded_occupancy" if occupied else None,
                            state,
                        ),
                    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date", type=date.fromisoformat, help="Eastern demo date (YYYY-MM-DD)"
    )
    parser.add_argument("--db", help="SQLite path")
    args = parser.parse_args()
    db = Database(args.db)
    db.initialize()
    seed(db, demo_date=args.date)
    print(f"Synthetic MemberGuide database ready: {db.path}")


if __name__ == "__main__":
    main()
