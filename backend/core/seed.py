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
    ("P7", "Dr. Elena Cruz", "cardiology", "10024", "212-555-0107", 1, ["METRO"]),
    (
        "P8",
        "Dr. Aaron Shah",
        "dermatology",
        "10023",
        "212-555-0108",
        1,
        ["METRO", "VALUE"],
    ),
    (
        "P9",
        "Dr. Priya Mehta",
        "cardiology",
        "10019",
        "212-555-0109",
        0,
        ["METRO", "VALUE"],
    ),
]
# A wider roster for the running service. It lives in ZIP areas the original six do
# not cover, so existing searches and tests are unchanged. Loaded by seed_expanded().
EXPANDED_PROVIDERS = [
    ("P7", "Dr. Priya Nair", "primary care", "10001", "212-555-0107", 1, ["METRO"]),
    ("P8", "Dr. Elena Vasquez", "primary care", "10001", "212-555-0108", 1, ["VALUE"]),
    ("P9", "Dr. Hannah Brooks", "primary care", "10011", "212-555-0109", 0, ["METRO"]),
    ("P10", "Dr. Aisha Rahman", "primary care", "10011", "212-555-0110", 1, ["METRO"]),
    (
        "P11",
        "Chelsea Community Health",
        "primary care",
        "10001",
        "212-555-0111",
        1,
        ["METRO", "VALUE"],
    ),
    ("P12", "Dr. Mei Tanaka", "primary care", "10025", "212-555-0112", 1, ["VALUE"]),
    (
        "P13",
        "Dr. Rachel Goldberg",
        "primary care",
        "10025",
        "212-555-0113",
        1,
        ["METRO"],
    ),
    (
        "P14",
        "Riverside Family Practice",
        "primary care",
        "10025",
        "212-555-0114",
        1,
        ["METRO", "VALUE"],
    ),
    ("P15", "Dr. Sofia Marin", "primary care", "10128", "212-555-0115", 1, ["METRO"]),
    ("P16", "Dr. Olivia Grant", "primary care", "10128", "212-555-0116", 1, ["VALUE"]),
    (
        "P17",
        "East Side Primary Care",
        "primary care",
        "10128",
        "212-555-0117",
        1,
        ["METRO", "VALUE"],
    ),
]
GOLD_PREV = "One annual preventive visit with an in-network primary care provider is covered at no cost share when billed as preventive. Other services during the visit may be billed separately."
BASIC_PREV = "One annual preventive visit with an in-network primary care provider is covered when billed as preventive. Other services may be billed separately."


def seed(db, *, demo_date=None, care_journeys=False):
    if db.environment != "synthetic":
        raise ValueError("Synthetic fixtures are forbidden in production")
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
            "INSERT OR IGNORE INTO plans(id,name,network,specialist_referral_required) VALUES (?,?,?,?)",
            [("GOLD", "Gold 2026", "METRO", 0), ("BASIC", "Basic 2026", "VALUE", 1)],
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
                (
                    "M4",
                    "Tessa Brooks",
                    "Tessa B.",
                    "7734",
                    2,
                    "BASIC",
                    "2026-01-01",
                    "2026-12-31",
                ),
                (
                    "M5",
                    "Jordan Blake",
                    "Jordan B.",
                    "6652",
                    11,
                    "BASIC",
                    "2026-01-01",
                    "2026-12-31",
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

    if care_journeys:
        from .care_fixtures import seed_care_journeys

        return seed_care_journeys(db, demo_date)
    return None


def seed_expanded(db, *, demo_date=None):
    if db.environment != "synthetic":
        raise ValueError("Synthetic fixtures are forbidden in production")
    """Add the wider roster and ten business days of 30-minute slots. Safe to repeat."""
    demo_date = demo_date or db.now().astimezone(EASTERN).date()
    days = []
    day = demo_date
    while len(days) < 10:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    with db.transaction() as conn:
        for index, (*provider, networks) in enumerate(EXPANDED_PROVIDERS):
            pid = provider[0]
            conn.execute(
                "INSERT OR IGNORE INTO providers VALUES (?,?,?,?,?,?)", provider
            )
            conn.executemany(
                "INSERT OR IGNORE INTO provider_networks VALUES (?,?)",
                [(pid, network) for network in networks],
            )
            for day_index, day in enumerate(days):
                for cell in range(16):
                    hour, minute = 9 + cell // 2, (cell % 2) * 30
                    # A lived-in schedule: roughly 40% taken, different for each doctor.
                    occupied = (cell * 3 + day_index * 2 + index) % 5 < 2
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
    parser.add_argument(
        "--care-journeys",
        action="store_true",
        help="Add completed PCP visits, referrals and rescheduling fixtures",
    )
    parser.add_argument(
        "--export",
        help="Write the synthetic journey manifest as JSON (requires --care-journeys)",
    )
    args = parser.parse_args()
    if args.export and not args.care_journeys:
        parser.error("--export requires --care-journeys")
    db = Database(args.db)
    db.initialize()
    manifest = seed(db, demo_date=args.date, care_journeys=args.care_journeys)
    if args.export:
        import json
        from pathlib import Path

        Path(args.export).write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Synthetic MemberGuide database ready: {db.path}")


if __name__ == "__main__":
    main()
