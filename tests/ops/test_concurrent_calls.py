"""Concurrent calls against the REAL core app (ops mounted by core's create_app) and one
shared SQLite database. Calls are driven through core's own agent routes, then read back
through the console routes. Synthetic members only; no external calls."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.core.db import Database
from backend.core.seed import seed
from backend.main import create_app
from backend.ops import clock as ops_clock

KEY = {"Authorization": "Bearer mc-key"}


class Clk:
    def __init__(self):
        self.value = datetime(2026, 11, 6, 21, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds=1):
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def clk(monkeypatch):
    c = Clk()
    monkeypatch.setattr(ops_clock, "now", c)  # ops and core read the same clock
    return c


@pytest.fixture
def web(tmp_path, clk):
    db = Database(tmp_path / "multi.db", clock=clk)
    db.initialize()
    seed(db, demo_date=clk().date())
    app = create_app(database=db, agent_key="mc-key")
    from tests.security_helpers import TOKENS, configure_roles

    configure_roles(app, tmp_path / "credentials.json", "mc-key")

    class AuthorizedClient(TestClient):
        def request(self, method, url, **kwargs):
            headers = dict(kwargs.pop("headers", {}) or {})
            if not any(k.lower() == "authorization" for k in headers):
                role = "admin" if str(url).startswith("/admin/") else "operator"
                headers["Authorization"] = "Bearer " + TOKENS[role]
            return super().request(method, url, headers=headers, **kwargs)

    with AuthorizedClient(app) as c:
        yield c


class Caller:
    """One simulated phone session: its own room, call id and turn counter."""

    def __init__(self, web, clk, room):
        self.web, self.clk, self.room, self.n = web, clk, room, 0
        self.headers = {
            **KEY,
            "X-Call-Key": f"test-call-capability-{room}-at-least-32-characters",
        }
        r = web.post("/calls", json={"room": room}, headers=self.headers)
        assert r.status_code == 201, r.text
        self.id = r.json()["call_id"]
        self.token = None

    def turn(self, role, text):
        self.n += 1
        r = self.web.post(
            f"/calls/{self.id}/turn",
            json={
                "client_turn_id": f"{self.room}-{self.n}",
                "role": role,
                "text": text,
            },
            headers=self.headers,
        )
        assert r.status_code in (200, 201), r.text
        return r

    def post(self, path, body=None):
        return self.web.post(
            f"/calls/{self.id}/{path}", json=body or {}, headers=self.headers
        )

    def verify(self, digits, month):
        r = self.post("verify", {"member_digits": digits, "birth_month": month})
        assert r.status_code == 200, r.text

    def search(self):
        assert (
            self.post(
                "providers", {"specialty": "primary care", "zip": "10023"}
            ).status_code
            == 200
        )

    def choose(self, provider="P2"):
        assert self.post("select", {"provider_id": provider}).status_code == 200
        today = self.web.get("/now", headers=KEY).json()["business_date"]
        r = self.post(
            "availability",
            {"date_from": today, "date_to": "2026-11-20", "part_of_day": "any"},
        )
        assert r.status_code == 200, r.text
        return r.json()["slots"]

    def read_back(self, slot_id):
        assert self.post("slot", {"slot_id": slot_id}).status_code == 200
        self.token = self.post("appointment/preview").json()["token"]
        assert self.post("appointment/armed", {"token": self.token}).status_code == 200

    def book(self):
        self.clk.advance()
        self.turn("user", "yes please")
        r = self.post("appointment/confirm", {"token": self.token})
        assert r.status_code == 201, r.text
        return r.json()["appointment"]["confirmation"]

    def followup(self, detail):
        r = self.post("followup", {"category": "caller_requested", "detail": detail})
        assert r.status_code == 201, r.text
        return r.json()["task"]

    def finalize(self):
        return self.post("finalize").json()["summary"]


def listing(web):
    r = web.get("/calls")
    assert r.status_code == 200
    return r.json()["calls"]


def state(web, call_id):
    r = web.get(f"/calls/{call_id}/state")
    assert r.status_code == 200, r.text
    return r.json()["state"]


def by_id(calls):
    return {c["call_id"]: c for c in calls}


def texts(st):
    return [t["text"] for t in st["turns"]]


def two_calls(web, clk):
    a = Caller(web, clk, "call-A")
    clk.advance()
    b = Caller(web, clk, "call-B")
    return a, b


# ---------------------------------------------------------------- scenarios


def test_a_interleaved_calls_both_active_and_isolated(web, clk):
    a, b = two_calls(web, clk)
    for who, role, text in [
        (a, "user", "four four one seven, April"),
        (b, "user", "two two six one, June"),
        (a, "assistant", "A-ONLY: thanks, verifying you"),
        (b, "assistant", "B-ONLY: thanks, verifying you"),
        (a, "user", "A-ONLY: I need a primary care doctor"),
        (b, "user", "B-ONLY: I need to speak to a person"),
    ]:
        clk.advance()
        who.turn(role, text)
    calls = listing(web)
    assert {c["call_id"] for c in calls} == {a.id, b.id}
    assert all(c["status"] == "live" for c in calls)
    sa, sb = state(web, a.id), state(web, b.id)
    assert sa["call_id"] == a.id and sb["call_id"] == b.id
    assert not any("B-ONLY" in t for t in texts(sa))
    assert not any("A-ONLY" in t for t in texts(sb))
    assert len(sa["turns"]) == len(sb["turns"]) == 3
    # verification answers are redacted per call, in the console projection only
    assert (
        sa["turns"][0]["text"]
        == sb["turns"][0]["text"]
        == "[Demo verification details redacted]"
    )
    # the list carries counts only: no transcript text at all
    summary = by_id(calls)
    assert "last_turn" not in summary[a.id] and "last_turn" not in summary[b.id]
    assert "A-ONLY" not in str(calls) and "B-ONLY" not in str(calls)
    assert summary[a.id]["turn_count"] == summary[b.id]["turn_count"] == 3
    # neither is verified, and neither leaks a member
    assert all(c["member"] is None and c["stage"] == "unverified" for c in calls)


def test_b_updating_one_call_leaves_the_other_untouched(web, clk):
    a, b = two_calls(web, clk)
    a.turn("user", "A-ONLY hello")
    before_a = state(web, a.id)
    before_list = by_id(listing(web))
    clk.advance(5)
    b.turn("user", "B-ONLY a brand new message")
    b.verify("2261", 6)
    assert state(web, a.id) == before_a  # byte-for-byte the same state for A
    sb = state(web, b.id)
    assert "B-ONLY a brand new message" in texts(sb) and sb["verified"] is True
    after_list = by_id(listing(web))
    assert after_list[a.id] == before_list[a.id]
    assert after_list[b.id]["last_activity_at"] > before_list[b.id]["last_activity_at"]
    assert after_list[b.id]["member"]["name"] == "Riley C."


def test_c_booking_for_a_and_followup_for_b_do_not_contaminate(web, clk):
    a, b = two_calls(web, clk)
    a.verify("4417", 4)
    a.search()
    slots = a.choose()
    a.read_back(slots[0]["slot_id"])
    confirmation = a.book()
    b.verify("2261", 6)
    b.turn("user", "B-ONLY please have someone call me")
    task = b.followup("B-ONLY wants a callback")
    sa, sb = state(web, a.id), state(web, b.id)
    assert sa["appointment"]["confirmation"] == confirmation and sa["tasks"] == []
    assert sb["appointment"] is None and sb["draft"] is None
    assert [t["call_id"] for t in sb["tasks"]] == [b.id] == [task["call_id"]]
    assert sa["member"]["name"] == "Maya T." and sb["member"]["name"] == "Riley C."
    summary = by_id(listing(web))
    assert (
        summary[a.id]["stage"] == "booked"
        and summary[a.id]["confirmation"] == confirmation
    )
    assert summary[b.id]["confirmation"] is None and summary[b.id]["open_tasks"] == 1
    assert summary[a.id]["open_tasks"] == 0
    # the operator task list holds exactly B's task, attached to B
    tasks = web.get("/tasks").json()["tasks"]
    assert [t["call_id"] for t in tasks] == [b.id]
    # finalizing builds each summary from that call's own rows
    assert a.finalize()["confirmation"] == confirmation
    sb_summary = b.finalize()
    assert sb_summary["outcome"] == "followup" and sb_summary["confirmation"] is None


def test_d_finalizing_a_moves_it_to_recent_while_b_stays_active(web, clk):
    a, b = two_calls(web, clk)
    a.turn("user", "A-ONLY hi")
    b.turn("user", "B-ONLY hi")
    clk.advance()
    a.finalize()
    calls = listing(web)
    assert [c["call_id"] for c in calls] == [b.id, a.id]  # live first, then finished
    assert by_id(calls)[a.id]["status"] == "finalized"
    assert by_id(calls)[b.id]["status"] == "live"
    assert (
        state(web, a.id)["status"] == "finalized"
        and state(web, b.id)["status"] == "live"
    )
    assert web.post("/admin/reset", json={}).json()["error"] == "CALL_ACTIVE"
    b.finalize()
    assert {c["status"] for c in listing(web)} == {"finalized"}
    assert web.post("/admin/reset", json={}).status_code == 200
    assert listing(web) == []


def test_e_a_third_call_appears_without_disturbing_the_others(web, clk):
    a, b = two_calls(web, clk)
    a.turn("user", "A-ONLY hi")
    b.turn("user", "B-ONLY hi")
    sa, sb = state(web, a.id), state(web, b.id)
    clk.advance(3)
    c = Caller(web, clk, "call-C")
    c.turn("user", "C-ONLY hello")
    ids = [x["call_id"] for x in listing(web)]
    assert ids == [c.id, b.id, a.id]  # newest first
    assert state(web, a.id) == sa and state(web, b.id) == sb
    assert texts(state(web, c.id)) == ["C-ONLY hello"]
    assert (
        web.get("/calls/latest").json()["state"]["call_id"] == c.id
    )  # latest kept for old consumers


def test_five_simultaneous_calls_stay_separate(web, clk):
    callers = []
    for i in range(5):
        callers.append(Caller(web, clk, f"call-{i}"))
        clk.advance()
    for rnd in range(3):  # interleave rounds across all five
        for i, caller in enumerate(callers):
            clk.advance()
            caller.turn("user", f"MARK-{i}-round-{rnd}")
    for i, caller in enumerate(callers):
        assert texts(state(web, caller.id)) == [f"MARK-{i}-round-{r}" for r in range(3)]
    assert len(listing(web)) == 5


# ---------------------------------------------------------------- edges


def test_unknown_call_id_is_not_found_and_never_falls_back(web, clk):
    Caller(web, clk, "call-A")
    r = web.get("/calls/call_does_not_exist/state")
    assert r.status_code == 404 and r.json()["error"] == "CALL_NOT_FOUND"
    assert set(r.json()) == {"error", "speak"}


def test_empty_list_and_latest(web):
    assert web.get("/calls").json() == {"calls": [], "speak": ""}
    assert web.get("/calls/latest").json() == {"state": None, "speak": ""}


def test_recent_cap_and_validation(web, clk):
    callers = [Caller(web, clk, f"call-{i}") for i in range(4)]
    for c in callers:
        clk.advance()
        c.finalize()
    assert len(listing(web)) == 4
    assert len(web.get("/calls?recent=2").json()["calls"]) == 2
    assert web.get("/calls?recent=0").json()["calls"] == []
    bad = web.get("/calls?recent=-1")
    assert bad.status_code == 422 and bad.json()["error"] == "INVALID_REQUEST"
    # most recently finished first
    finished = [c["call_id"] for c in web.get("/calls?recent=2").json()["calls"]]
    assert finished == [callers[3].id, callers[2].id]


def test_stage_follows_each_calls_own_progress(web, clk):
    a, b = two_calls(web, clk)
    stage = lambda c: by_id(listing(web))[c.id]["stage"]  # noqa: E731
    assert stage(a) == "unverified"
    a.verify("4417", 4)
    assert stage(a) == "verified" and stage(b) == "unverified"
    a.search()
    assert stage(a) == "searching"
    slots = a.choose()
    assert stage(a) == "offering"
    a.post("slot", {"slot_id": slots[0]["slot_id"]})
    assert stage(a) == "readback"
    a.token = a.post("appointment/preview").json()["token"]
    a.post("appointment/armed", {"token": a.token})
    assert stage(a) == "awaiting_yes" and stage(b) == "unverified"
    a.book()
    assert stage(a) == "booked"


def test_list_never_exposes_secrets(web, clk):
    a, _ = two_calls(web, clk)
    a.turn("user", "my digits are 4417 and I was born in April")
    a.verify("4417", 4)
    a.search()
    slots = a.choose()
    a.read_back(slots[0]["slot_id"])
    blob = json.dumps(web.get("/calls").json()).lower()
    for secret in (
        "token",
        "details_hash",
        "member_digits",
        "birth_month",
        a.token.lower(),
    ):
        assert secret not in blob
    assert by_id(listing(web))[a.id]["member"]["id_masked"] == "***4417"
