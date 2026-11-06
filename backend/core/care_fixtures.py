"""Opt-in synthetic care history; no invented voice calls, tokens or consent.

Install into a fresh demo DB with `python -m backend.core.seed --care-journeys`.
The manifest is persisted so reseeding never undoes subsequent user actions.
"""

import json
from datetime import datetime, time, timedelta

from .common import EASTERN, utc

FIXTURE_SET = "care-journeys-v2"


def business_day(day, offset):
    direction = 1 if offset >= 0 else -1
    remaining = abs(offset)
    while remaining:
        day += timedelta(days=direction)
        if day.weekday() < 5:
            remaining -= 1
    return day


def fixture_slot(conn, provider_id, day, hour, minute, state):
    slot_id = f"S-{provider_id}-{day:%Y%m%d}-{hour:02}{minute:02}"
    start = datetime.combine(day, time(hour, minute), tzinfo=EASTERN)
    if conn.execute(
        "SELECT 1 FROM appointments WHERE slot_id=? AND status IN ('booked','completed')",
        (slot_id,),
    ).fetchone():
        raise ValueError(
            "Fixture slot has an existing appointment; use a fresh demo database"
        )
    conn.execute(
        "INSERT INTO slots(id,provider_id,starts_at,ends_at,state,occupancy_reason,seed_state) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
        "state=excluded.state,occupancy_reason=excluded.occupancy_reason,seed_state=excluded.seed_state",
        (
            slot_id,
            provider_id,
            utc(start),
            utc(start + timedelta(minutes=30)),
            state,
            "seeded_occupancy" if state == "booked" else None,
            state,
        ),
    )
    return conn.execute("SELECT * FROM slots WHERE id=?", (slot_id,)).fetchone()


def fixture_appointment(
    conn, appointment_id, member_id, slot, status, created_at, referral_id=None
):
    conn.execute(
        "INSERT INTO appointments(id,member_id,provider_id,slot_id,confirmation,status,"
        "starts_at,ends_at,created_at,source,referral_id) VALUES (?,?,?,?,?,?,?,?,?,'synthetic_fixture',?)",
        (
            appointment_id,
            member_id,
            slot["provider_id"],
            slot["id"],
            f"MG-DEMO-{appointment_id.removeprefix('FIX-')}",
            status,
            slot["starts_at"],
            slot["ends_at"],
            created_at,
            referral_id,
        ),
    )
    conn.execute(
        "UPDATE slots SET occupancy_reason='appointment' WHERE id=?", (slot["id"],)
    )


def seed_care_journeys(db, demo_date):
    with db.transaction() as conn:
        saved = conn.execute(
            "SELECT * FROM demo_fixture_sets WHERE id=?", (FIXTURE_SET,)
        ).fetchone()
        if saved:
            if saved["demo_date"] != demo_date.isoformat():
                raise ValueError(
                    "Care fixtures use a different demo date; choose a fresh --db path"
                )
            return json.loads(saved["manifest_json"])
        if conn.execute("SELECT 1 FROM calls WHERE status='live'").fetchone():
            raise ValueError("Finish live calls before installing care fixtures")
        created_at = utc(
            datetime.combine(business_day(demo_date, -5), time(8), tzinfo=EASTERN)
        )
        for member_id, provider_id, hour in [
            ("M1", "P4", 9),
            ("M2", "P3", 10),
            ("M4", "P3", 11),
            ("M5", "P4", 14),
        ]:
            slot = fixture_slot(
                conn, provider_id, business_day(demo_date, -3), hour, 0, "booked"
            )
            fixture_appointment(
                conn,
                f"FIX-{member_id}-PCP-COMPLETED",
                member_id,
                slot,
                "completed",
                created_at,
            )
        for (
            referral_id,
            member_id,
            provider_id,
            specialty,
            status,
            valid_from,
            valid_until,
        ) in [
            ("REF-M1-DERM", "M1", "P4", "dermatology", "reported", None, None),
            (
                "REF-M2-CARD",
                "M2",
                "P3",
                "cardiology",
                "verified",
                demo_date - timedelta(days=7),
                demo_date + timedelta(days=7),
            ),
            (
                "REF-M5-DERM",
                "M5",
                "P4",
                "dermatology",
                "verified",
                demo_date - timedelta(days=30),
                demo_date - timedelta(days=1),
            ),
            (
                "REF-M5-CARD",
                "M5",
                "P4",
                "cardiology",
                "revoked",
                demo_date - timedelta(days=7),
                demo_date + timedelta(days=30),
            ),
        ]:
            conn.execute(
                "INSERT INTO referrals(id,member_id,referring_provider_id,referring_appointment_id,"
                "specialty,status,valid_from,valid_until,source,created_at) VALUES (?,?,?,?,?,?,?,?,'synthetic_fixture',?)",
                (
                    referral_id,
                    member_id,
                    provider_id,
                    f"FIX-{member_id}-PCP-COMPLETED",
                    specialty,
                    status,
                    valid_from.isoformat() if valid_from else None,
                    valid_until.isoformat() if valid_until else None,
                    utc(
                        datetime.combine(
                            business_day(demo_date, -3), time(16), tzinfo=EASTERN
                        )
                    ),
                ),
            )
        cases = []
        for key, member_id, provider_id, day_offset, hour, minute, referral_id in [
            ("maya-pcp", "M1", "P2", 2, 9, 30, None),
            ("riley-pcp", "M2", "P4", 4, 10, 0, None),
            ("maya-specialist", "M1", "P8", 4, 13, 0, "REF-M1-DERM"),
            ("riley-specialist", "M2", "P6", 2, 11, 0, "REF-M2-CARD"),
        ]:
            original = fixture_slot(
                conn,
                provider_id,
                business_day(demo_date, day_offset),
                hour,
                minute,
                "booked",
            )
            appointment_id = f"FIX-{key.upper()}-BOOKED"
            fixture_appointment(
                conn,
                appointment_id,
                member_id,
                original,
                "booked",
                created_at,
                referral_id,
            )
            target_hour = 14 if key == "riley-specialist" else hour
            target = fixture_slot(
                conn,
                provider_id,
                business_day(demo_date, day_offset + 1),
                target_hour,
                minute,
                "open",
            )
            unavailable = fixture_slot(
                conn,
                provider_id,
                business_day(demo_date, day_offset + 1),
                target_hour,
                30 if minute == 0 else 0,
                "booked",
            )
            cases.append(
                {
                    "id": f"reschedule-{key}",
                    "member_id": member_id,
                    "appointment_id": appointment_id,
                    "provider_id": provider_id,
                    "specialty": "primary care"
                    if "pcp" in key
                    else ("cardiology" if member_id == "M2" else "dermatology"),
                    "original_slot_id": original["id"],
                    "replacement_slot_id": target["id"],
                    "unavailable_slot_id": unavailable["id"],
                    "referral_id": referral_id,
                    "expected": "move_atomically_after_new_consent",
                    "on_conflict": "keep_original_booked",
                }
            )
        cases.extend(
            [
                {
                    "id": "specialist-no-referral-required",
                    "member_id": "M1",
                    "specialty": "dermatology",
                    "referral_id": "REF-M1-DERM",
                    "provider_id": "P8",
                    "expected": "eligible_without_formal_referral",
                    "evidence_id": "GOLD-REF",
                },
                {
                    "id": "specialist-valid-referral",
                    "member_id": "M2",
                    "specialty": "cardiology",
                    "referral_id": "REF-M2-CARD",
                    "provider_id": "P6",
                    "expected": "eligible_with_verified_referral",
                    "evidence_id": "BASIC-REF",
                },
                {
                    "id": "specialist-missing-referral",
                    "member_id": "M4",
                    "specialty": "cardiology",
                    "referral_id": None,
                    "provider_id": "P6",
                    "expected": "referral_required_followup",
                    "evidence_id": "BASIC-REF",
                },
                {
                    "id": "specialist-expired-referral",
                    "member_id": "M5",
                    "specialty": "dermatology",
                    "referral_id": "REF-M5-DERM",
                    "provider_id": "P8",
                    "expected": "referral_required_followup",
                    "evidence_id": "BASIC-REF",
                },
                {
                    "id": "specialist-revoked-referral",
                    "member_id": "M5",
                    "specialty": "cardiology",
                    "referral_id": "REF-M5-CARD",
                    "provider_id": "P6",
                    "expected": "referral_required_followup",
                    "evidence_id": "BASIC-REF",
                },
                {
                    "id": "specialist-not-accepting",
                    "member_id": "M1",
                    "specialty": "cardiology",
                    "provider_id": "P9",
                    "expected": "visit_type_unavailable",
                },
                {
                    "id": "specialist-out-of-network",
                    "member_id": "M1",
                    "specialty": "cardiology",
                    "provider_id": "P6",
                    "expected": "not_bookable",
                },
                {
                    "id": "specialist-no-availability",
                    "member_id": "M1",
                    "specialty": "dermatology",
                    "provider_id": "P5",
                    "expected": "no_availability_followup",
                },
            ]
        )
        later_slot = fixture_slot(conn, "P6", business_day(demo_date, 6), 11, 0, "open")
        cases.append(
            {
                "id": "reschedule-specialist-referral-expires-before-new-date",
                "member_id": "M2",
                "appointment_id": "FIX-RILEY-SPECIALIST-BOOKED",
                "provider_id": "P6",
                "specialty": "cardiology",
                "referral_id": "REF-M2-CARD",
                "replacement_slot_id": later_slot["id"],
                "expected": "referral_required_keep_original_booked",
            }
        )
        members = [
            dict(row)
            for row in conn.execute(
                "SELECT id AS member_id,display_name,member_digits,birth_month,plan_id FROM members ORDER BY id"
            )
        ]
        manifest = {
            "fixture_set": FIXTURE_SET,
            "demo_date": demo_date.isoformat(),
            "timezone": "America/New_York",
            "synthetic": True,
            "members": members,
            "cases": cases,
            "plans": [
                dict(row) for row in conn.execute("SELECT * FROM plans ORDER BY id")
            ],
            "providers": [
                {
                    **dict(row),
                    "networks": [
                        network[0]
                        for network in conn.execute(
                            "SELECT network FROM provider_networks WHERE provider_id=? ORDER BY network",
                            (row["id"],),
                        )
                    ],
                }
                for row in conn.execute("SELECT * FROM providers ORDER BY id")
            ],
            "appointments": [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM appointments WHERE source='synthetic_fixture' ORDER BY id"
                )
            ],
            "referrals": [
                dict(row) for row in conn.execute("SELECT * FROM referrals ORDER BY id")
            ],
        }
        slot_ids = {appointment["slot_id"] for appointment in manifest["appointments"]}
        for case in cases:
            for key in (
                "original_slot_id",
                "replacement_slot_id",
                "unavailable_slot_id",
            ):
                if key in case:
                    slot_ids.add(case[key])
        manifest["slots"] = [
            dict(conn.execute("SELECT * FROM slots WHERE id=?", (slot_id,)).fetchone())
            for slot_id in sorted(slot_ids)
        ]
        conn.execute(
            "INSERT INTO demo_fixture_sets VALUES (?,?,?,?)",
            (FIXTURE_SET, demo_date.isoformat(), json.dumps(manifest), utc(db.now())),
        )
        return manifest
