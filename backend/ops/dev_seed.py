"""DEV ONLY. Builds a SQLite database from contracts/schema.sql with synthetic fixtures,
and writes a synthetic call at a chosen stage so the console can be verified without the
core routes. Core's seed (data/seed.py) replaces this in the real app.

    uv run python -m backend.ops.dev_seed --db /tmp/careline.db init
    uv run python -m backend.ops.dev_seed --db /tmp/careline.db stage armed
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import clock
from .db import connect
from .summary import finalize_call
from .tasks import create_task

SCHEMA = Path(__file__).resolve().parents[2] / "contracts" / "schema.sql"
STAGES = [
    "unverified",
    "verified",
    "offered",
    "preview",
    "armed",
    "conflict",
    "booked",
    "finalized",
    "followup",
    "locked",
]

GOLD_PREV = (
    "One annual preventive visit with an in-network primary care provider is covered at no cost share "
    "when billed as preventive. Other services during the visit may be billed separately."
)
FIRST_REQUEST = "Find a new-patient primary care doctor near 10023 and book a visit."
READ_BACK = (
    "Maya, this is a simulated new-patient primary care visit in person with Dr. Omar Haddad on {when}. "
    "Would you like me to book that exact appointment in the demo schedule?"
)
PROVIDERS = [
    ("P1", "Dr. Lena Park", "10019", "212-555-0101", 0, ["METRO"]),
    ("P2", "Dr. Omar Haddad", "10023", "212-555-0102", 1, ["METRO"]),
    ("P3", "Dr. Grace Liu", "10019", "212-555-0103", 1, ["VALUE"]),
    ("P4", "Westside Family Medicine", "10024", "212-555-0104", 1, ["METRO", "VALUE"]),
]


def _ts(dt: datetime) -> str:
    return clock.utc_str(dt)


def target_day(now: datetime) -> datetime:
    """The next Friday at least a day out, as an aware Eastern date at midnight."""
    local = now.astimezone(clock.ET).replace(hour=0, minute=0, second=0, microsecond=0)
    ahead = (4 - local.weekday()) % 7 or 7
    return local + timedelta(days=ahead)


def slot_id(provider: str, local: datetime) -> str:
    return f"S-{provider}-{local:%m%d}-{local:%H%M}"


def init_db(path: str | Path, now: datetime | None = None) -> sqlite3.Connection:
    if os.getenv("MEMBERGUIDE_ENV", "synthetic") != "synthetic":
        raise ValueError("Development fixtures are forbidden in production")
    now = now or clock.now()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if p.parent.stat().st_mode & 0o077:
        raise ValueError("Development database directory must be owner-only")
    if p.exists():
        previous = connect(p)
        try:
            if previous.execute(
                "SELECT 1 FROM sqlite_master WHERE name='deployment_scope'"
            ).fetchone():
                scope = previous.execute(
                    "SELECT environment FROM deployment_scope"
                ).fetchone()
                if scope and scope["environment"] != "synthetic":
                    raise ValueError("Cannot overwrite a production database")
        finally:
            previous.close()
        p.unlink()
    fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    conn = connect(p)
    conn.executescript(SCHEMA.read_text())
    conn.executescript(
        (SCHEMA.parent.parent / "backend" / "security_schema.sql").read_text()
    )
    conn.execute("INSERT INTO deployment_scope VALUES (1,'synthetic','synthetic')")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO plans VALUES ('plan_gold', 'Gold 2026', 'METRO'), ('plan_basic', 'Basic 2026', 'VALUE')"
    )
    conn.executemany(
        "INSERT INTO members VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "m_maya",
                "Maya Torres",
                "Maya T.",
                "4417",
                4,
                "plan_gold",
                "2026-01-01",
                "2026-12-31",
            ),
            (
                "m_riley",
                "Riley Chen",
                "Riley C.",
                "2261",
                6,
                "plan_basic",
                "2026-01-01",
                "2026-12-31",
            ),
            (
                "m_devon",
                "Devon Clarke",
                "Devon C.",
                "8832",
                9,
                "plan_basic",
                "2026-01-01",
                "2026-10-31",
            ),
        ],
    )
    conn.execute(
        "INSERT INTO plan_sections VALUES ('GOLD-PREV', 'plan_gold', 'preventive', 'Preventive care', ?)",
        (GOLD_PREV,),
    )
    for pid, name, zip_, phone, accepting, nets in PROVIDERS:
        conn.execute(
            "INSERT INTO providers VALUES (?, ?, 'primary care', ?, ?, ?)",
            (pid, name, zip_, phone, accepting),
        )
        for n in nets:
            conn.execute("INSERT INTO provider_networks VALUES (?, ?)", (pid, n))
    day = target_day(now)
    forced_open = {(14, 30), (15, 0), (16, 0)}
    for prov in ("P2", "P4"):
        for i in range(16):  # 9:00 .. 16:30 on a 30-minute grid
            local = day + timedelta(hours=9, minutes=30 * i)
            booked = (i % 5 in (1, 3)) and (local.hour, local.minute) not in forced_open
            start = local.astimezone(timezone.utc)
            conn.execute(
                "INSERT INTO slots (id, provider_id, starts_at, ends_at, state, occupancy_reason, seed_state) VALUES (?,?,?,?,?,?,?)",
                (
                    slot_id(prov, local),
                    prov,
                    _ts(start),
                    _ts(start + timedelta(minutes=30)),
                    "booked" if booked else "open",
                    "seeded_occupancy" if booked else None,
                    "booked" if booked else "open",
                ),
            )
    return conn


def _provider_json(row):
    return {
        "id": row[0],
        "name": row[1],
        "specialty": "primary care",
        "zip": row[2],
        "phone": row[3],
        "accepting_new_patients": bool(row[4]),
    }


def build_stage(
    conn: sqlite3.Connection, stage: str, base: datetime | None = None
) -> str:
    """(Re)write synthetic call ``c_01`` at ``stage``. ``base`` is the call's creation time."""
    if stage not in STAGES:
        raise SystemExit(f"unknown stage {stage!r}; choose from {', '.join(STAGES)}")
    base = (base or clock.now() - timedelta(seconds=50)).replace(microsecond=0)
    at = lambda secs: _ts(base + timedelta(seconds=secs))  # noqa: E731
    day = target_day(base)
    when_local = day + timedelta(hours=15)
    other_local = day + timedelta(hours=14, minutes=30)
    when_utc, other_utc = (
        when_local.astimezone(timezone.utc),
        other_local.astimezone(timezone.utc),
    )
    chosen, other = slot_id("P2", when_local), slot_id("P2", other_local)

    # clear any previous synthetic call (and its effects) so the stage is deterministic
    conn.execute(
        "UPDATE slots SET state = seed_state, occupancy_reason = CASE seed_state WHEN 'booked' THEN 'seeded_occupancy' END"
    )
    with_tx = not conn.in_transaction
    if with_tx:
        conn.execute("BEGIN IMMEDIATE")
    conn.execute("UPDATE calls SET current_draft_id = NULL")
    for table in ("identity_reviews", "call_access", "legal_holds"):
        conn.execute(f"DELETE FROM {table}")
    for t in ("tasks", "events", "appointments", "drafts", "turns", "calls"):
        conn.execute(f"DELETE FROM {t}")

    s = STAGES.index(stage)
    locked = stage == "locked"
    verified = s >= 1 and not locked
    searched = s >= 2 and stage != "locked"
    offered = s >= 2 and stage != "locked"
    slot_chosen = stage in ("preview", "armed", "conflict", "booked", "finalized")
    previewed = stage in ("preview", "armed", "conflict", "booked", "finalized")
    armed = stage in ("armed", "conflict", "booked", "finalized")
    booked = stage in ("booked", "finalized")

    offered_json = json.dumps(
        [
            {
                "slot_id": sid,
                "provider_id": "P2",
                "starts_at": _ts(u),
                "ends_at": _ts(u + timedelta(minutes=30)),
                "timezone": "America/New_York",
                "text": clock.spoken(_ts(u)),
            }
            for sid, u in ((other, other_utc), (chosen, when_utc))
        ]
        if offered
        and stage != "conflict"  # a failed confirm clears the offers (contract)
        else []
    )
    conn.execute(
        "INSERT INTO calls (id, room, status, created_at, verification_status, verification_attempts, member_id, request_version, "
        "specialty, zip, selected_provider_id, providers_json, excluded_json, evidence_json, availability_query_json, offered_slots_json, first_request) "
        "VALUES ('c_01', 'dev-room', 'live', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            at(0),
            "locked" if locked else "verified" if verified else "unverified",
            3 if locked else 1 if verified else 0,
            "m_maya" if verified else None,
            3 if searched else 0,
            "primary care" if searched else None,
            "10023" if searched else None,
            "P2" if searched else None,
            json.dumps(
                [_provider_json(PROVIDERS[1]), _provider_json(PROVIDERS[3])]
                if searched
                else []
            ),
            json.dumps(
                [
                    {
                        "id": "P1",
                        "name": "Dr. Lena Park",
                        "reason_code": "VISIT_TYPE_UNAVAILABLE",
                        "reason": "not accepting new patients",
                    },
                    {
                        "id": "P3",
                        "name": "Dr. Grace Liu",
                        "reason_code": "NOT_BOOKABLE",
                        "reason": "out of network",
                    },
                ]
                if searched
                else []
            ),
            json.dumps(
                [{"id": "GOLD-PREV", "title": "Preventive care", "text": GOLD_PREV}]
                if searched
                else []
            ),
            json.dumps(
                {
                    "date_from": f"{day:%Y-%m-%d}",
                    "date_to": f"{day:%Y-%m-%d}",
                    "part_of_day": "afternoon",
                }
            )
            if offered
            else None,
            offered_json,
            FIRST_REQUEST if s >= 2 or stage == "locked" else None,
        ),
    )

    # --- turns
    turns: list[tuple[int, str, str, int]] = []
    if locked:
        turns = [
            (1, "user", "My digits are one two three four, born in May.", 3),
            (
                2,
                "assistant",
                "Those details did not match. Please try the four digits and birth month again.",
                6,
            ),
            (3, "user", "Nine nine nine nine, March.", 12),
            (
                4,
                "assistant",
                "I couldn't verify those details after three tries. I've saved a follow-up request.",
                16,
            ),
        ]
    elif s >= 1:
        turns = [
            (1, "user", "Maya Torres, four four one seven, April.", 2),
            (2, "assistant", "Thank you, Maya. Your demo details are verified.", 5),
        ]
    if s >= 2 and not locked:
        turns.append((3, "user", FIRST_REQUEST, 12))
    if armed:
        turns.append(
            (4, "assistant", READ_BACK.format(when=clock.spoken(_ts(when_utc))), 35)
        )
    if booked:
        turns.append((5, "user", "Yes please.", 45))
    for seq, role, text, secs in turns:
        conn.execute(
            "INSERT INTO turns VALUES ('c_01', ?, ?, ?, ?, ?)",
            (seq, f"cid-{seq}", role, text, at(secs)),
        )

    # --- events (contract order)
    names = ["call_created"]
    if verified:
        names.append("verified")
    if locked:
        names += ["verification_failed", "verification_failed", "verification_locked"]
    if searched:
        names += ["providers_searched", "provider_selected"]
    if offered:
        names.append("availability_offered")
    if slot_chosen:
        names.append("slot_selected")
    if previewed:
        names.append("preview_created")
    if armed:
        names.append("confirmation_armed")
    if stage == "conflict":
        names += ["slot_taken", "preview_invalidated"]
    if booked:
        names.append("booked")
    # An event is stored after the turn that caused it (the verify call follows the user turn).
    when_secs = {
        "call_created": 0,
        "verified": 3,
        "verification_failed": 7,
        "verification_locked": 17,
        "providers_searched": 14,
        "provider_selected": 15,
        "availability_offered": 20,
        "slot_selected": 28,
        "preview_created": 33,
        "confirmation_armed": 40,
        "slot_taken": 44,
        "preview_invalidated": 44,
        "booked": 46,
        "followup_created": 30,
    }
    for n in names:
        conn.execute(
            "INSERT INTO events (call_id, name, created_at) VALUES ('c_01', ?, ?)",
            (n, at(when_secs.get(n, 0))),
        )

    # --- draft / appointment
    if slot_chosen:
        status = (
            "booked"
            if booked
            else "invalidated"
            if stage == "conflict"
            else "armed"
            if stage == "armed"
            else "preview"
        )
        details = hashlib.sha256(f"m_maya|P2|{chosen}".encode()).hexdigest()
        conn.execute(
            "INSERT INTO drafts (id, call_id, member_id, provider_id, slot_id, revision, request_version, status, token, details_hash, read_back, preview_user_seq, "
            "armed_seq, armed_at, expires_at, created_at) VALUES ('d_01','c_01','m_maya','P2',?,1,3,?,?,?,?,?,?,?,?,?)",
            (
                chosen,
                status,
                "dev-token-not-for-display",
                details,
                READ_BACK.format(when=clock.spoken(_ts(when_utc))),
                3,
                3 if armed else None,
                at(40) if armed else None,
                _ts(base + timedelta(seconds=130)) if armed else None,
                at(33),
            ),
        )
        conn.execute("UPDATE calls SET current_draft_id = 'd_01' WHERE id = 'c_01'")
    if stage == "conflict":
        conn.execute(
            "UPDATE slots SET state = 'blocked', occupancy_reason = 'simulated_other_caller' WHERE id = ?",
            (chosen,),
        )
    if booked:
        conn.execute(
            "UPDATE slots SET state = 'booked', occupancy_reason = 'appointment' WHERE id = ?",
            (chosen,),
        )
        conn.execute(
            "INSERT INTO appointments (id, call_id, member_id, provider_id, slot_id, draft_id, confirmation, status, starts_at, ends_at, consent_turn_seq, created_at) "
            "VALUES ('apt_01','c_01','m_maya','P2',?,'d_01','MG-APT-4821','booked',?,?,5,?)",
            (chosen, _ts(when_utc), _ts(when_utc + timedelta(minutes=30)), at(46)),
        )
    if with_tx:
        conn.execute("COMMIT")

    if stage == "followup":
        create_task(
            conn,
            "c_01",
            "caller_requested",
            "Caller requested a person; no live transfer is available in this demo.",
            "dev-followup",
        )
    if locked:
        create_task(
            conn,
            "c_01",
            "verification_failed",
            "Three failed verification attempts.",
            "dev-locked",
        )
    if stage in ("finalized", "followup", "locked"):
        finalize_call(conn, "c_01")
    return "c_01"


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser(
        "init", help="create the database with fixtures (deletes an existing file)"
    )
    st = sub.add_parser("stage", help="write call c_01 at a stage")
    st.add_argument("name", choices=STAGES)
    a = ap.parse_args()
    if a.cmd == "init":
        init_db(a.db).close()
        print(f"initialized {a.db}")
    else:
        conn = connect(a.db)
        build_stage(conn, a.name)
        conn.close()
        print(f"call c_01 is now at stage '{a.name}'")


if __name__ == "__main__":
    main()
