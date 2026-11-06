"""Stand-in for the real backend, so the voice agent can be built and tested alone.

Set USE_FAKE_BACKEND=1. Turn it OFF for the 5:30 checkpoint: the real backend is
Aneesh's and Siddhant's. This file also works as an executable copy of the booking
rules in docs/MEMBERGUIDE-FINAL-PLAN.md section 8, so a disagreement shows up here
first. Synthetic data only. Every visit is 30 minutes.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
YES_WINDOW_S = 90
VISIT_MIN = 30

MEMBERS = {
    "4417": {
        "name": "Maya Torres",
        "month": "april",
        "plan": "Gold 2026",
        "network": "METRO",
    }
}
PROVIDERS = {
    "P1": {
        "name": "Dr. Lena Park",
        "zip": "10019",
        "nets": {"METRO"},
        "new": False,
        "phone": "212-555-0101",
    },
    "P2": {
        "name": "Dr. Omar Haddad",
        "zip": "10023",
        "nets": {"METRO"},
        "new": True,
        "phone": "212-555-0102",
    },
    "P3": {
        "name": "Dr. Grace Liu",
        "zip": "10019",
        "nets": {"VALUE"},
        "new": True,
        "phone": "212-555-0103",
    },
    "P4": {
        "name": "Westside Family Medicine",
        "zip": "10024",
        "nets": {"METRO", "VALUE"},
        "new": True,
        "phone": "212-555-0104",
    },
}
NEAREST = {
    "10019": ["10019", "10023", "10024"],
    "10023": ["10023", "10024", "10019"],
    "10024": ["10024", "10023", "10019"],
}
PREVENTIVE = {
    "id": "GOLD-PREV",
    "title": "Preventive care",
    "text": "One annual preventive visit with an in-network primary care provider is covered at no cost "
    "share when billed as preventive. Other services during the visit may be billed separately.",
}
WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]
_NUMWORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "for": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

_YES = re.compile(
    r"^(?:yes|yeah|yep|yup|sure|ok|okay|correct|right|that'?s right|go ahead|please do|"
    r"book it|confirm|confirmed|sounds good|perfect|absolutely|definitely)"
    r"(?:\s+please)?[\s.!]*$",
    re.I,
)


def is_clear_yes(text: str) -> bool:
    """A yes with nothing added. 'Yes, but later' and 'hold on' are not a yes."""
    t = " ".join(text.replace("\u2019", "'").split())
    return bool(_YES.match(t.strip(" ,")))


def spoken(dt: datetime) -> str:
    h = dt.hour % 12 or 12
    return f"{dt:%A, %B} {dt.day} at {h}:{dt:%M} {'AM' if dt.hour < 12 else 'PM'}"


def _digits(text: str) -> str:
    out = []
    for tok in re.findall(r"[a-z]+|\d", text.lower()):
        out.append(tok if tok.isdigit() else _NUMWORDS.get(tok, ""))
    return "".join(out)


class FakeBackend:
    def __init__(self, now: datetime | None = None) -> None:
        self.now = now or datetime.now(ET)
        self.calls: dict[str, dict[str, Any]] = {}
        self.appointments: list[dict[str, Any]] = []
        self.tasks: list[dict[str, Any]] = []
        self.slots: dict[str, dict[str, Any]] = {}
        self._seed()

    # ---- schedule ----
    def _next(self, weekday: int) -> date:
        d = self.now.date() + timedelta(days=1)
        while d.weekday() != weekday:
            d += timedelta(days=1)
        return d

    def _add(self, pid: str, d: date, hhmm: str) -> None:
        h, m = map(int, hhmm.split(":"))
        start = datetime(d.year, d.month, d.day, h, m, tzinfo=ET)
        sid = f"S-{pid}-{start:%m%d-%H%M}"
        self.slots[sid] = {
            "id": sid,
            "provider": pid,
            "start": start,
            "end": start + timedelta(minutes=VISIT_MIN),
            "booked": False,
        }

    def _seed(self) -> None:
        thu, fri, wed = self._next(3), self._next(4), self._next(2)
        for t in ("09:30", "10:30"):
            self._add("P2", thu, t)
        for t in ("14:30", "15:00", "16:00"):
            self._add("P2", fri, t)
        self._add("P1", thu, "10:00")
        self._add("P4", wed, "13:00")

    def take_slot(self, slot_id: str) -> None:
        """Demo button: another caller takes this slot."""
        self.slots[slot_id]["booked"] = True

    # ---- calls ----
    def _c(self, call_id: str) -> dict[str, Any]:
        return self.calls[call_id]

    async def start_call(self, room: str) -> dict[str, Any]:
        cid = f"c_{len(self.calls) + 1:02d}"
        self.calls[cid] = {
            "room": room,
            "member": None,
            "tries": 0,
            "turns": [],
            "draft": None,
            "tasks": [],
        }
        return {"ok": True, "call_id": cid}

    async def verify(
        self, call_id: str, digits: str, birth_month: str
    ) -> dict[str, Any]:
        c = self._c(call_id)
        if c["tries"] >= 3:
            return {
                "ok": False,
                "error": "LOCKED",
                "speak": "I can't verify you on this call. I can file a request for our team.",
            }
        m = MEMBERS.get(_digits(digits))
        if m and m["month"] == birth_month.strip().lower():
            c["member"] = m
            return {
                "ok": True,
                "status": "verified",
                "speak": f"Thanks, {m['name'].split()[0]}. You're verified.",
            }
        c["tries"] += 1
        return {
            "ok": False,
            "error": "VERIFICATION_FAILED",
            "speak": "I couldn't match that. Let's try the last four digits again, one at a time.",
        }

    async def turn(self, call_id: str, role: str, text: str) -> dict[str, Any]:
        c = self._c(call_id)
        seq = len(c["turns"]) + 1
        c["turns"].append(
            {"seq": seq, "role": role, "text": text, "at": datetime.now(ET)}
        )
        return {"ok": True, "turn_seq": seq}

    # ---- search ----
    async def providers(
        self, call_id: str, specialty: str, zip_code: str
    ) -> dict[str, Any]:
        c = self._c(call_id)
        if not c["member"]:
            return {
                "ok": False,
                "error": "VERIFICATION_REQUIRED",
                "speak": "I'll need to verify you first.",
            }
        if specialty.strip().lower() not in {
            "primary care",
            "primary care doctor",
            "pcp",
            "family doctor",
        }:
            return {
                "ok": False,
                "error": "NO_MATCH",
                "speak": "This version only books primary care for new patients. I can file a request for our team.",
            }
        order = NEAREST.get(zip_code.strip())
        if not order:
            return {
                "ok": False,
                "error": "NO_MATCH",
                "speak": "I don't have doctors near that ZIP code in my list.",
            }
        net = c["member"]["network"]
        ok, out = [], []
        for pid, p in sorted(
            PROVIDERS.items(),
            key=lambda kv: order.index(kv[1]["zip"]) if kv[1]["zip"] in order else 9,
        ):
            if net not in p["nets"]:
                out.append({"id": pid, "name": p["name"], "reason": "out of network"})
            elif not p["new"]:
                out.append(
                    {
                        "id": pid,
                        "name": p["name"],
                        "reason": "not accepting new patients",
                    }
                )
            else:
                ok.append(
                    {"id": pid, "name": p["name"], "zip": p["zip"], "phone": p["phone"]}
                )
        ok = ok[:3]
        c["draft"] = None
        c["found"] = {p["id"] for p in ok}
        if not ok:
            return {
                "ok": False,
                "error": "NO_MATCH",
                "speak": "I couldn't find an in-network primary care doctor taking new patients there.",
                "excluded": out,
            }
        names = " or ".join(p["name"] for p in ok[:2])
        return {
            "ok": True,
            "providers": ok,
            "excluded": out,
            "speak": f"Near {zip_code}, I found {names}, both in your network and taking new patients.",
        }

    async def select(self, call_id: str, provider_id: str) -> dict[str, Any]:
        c = self._c(call_id)
        if provider_id not in c.get("found", set()):
            return {
                "ok": False,
                "error": "UNKNOWN_PROVIDER",
                "speak": "I don't have that doctor in these results.",
            }
        c["selected"] = provider_id
        return {
            "ok": True,
            "evidence": [PREVENTIVE],
            "phone": PROVIDERS[provider_id]["phone"],
            "speak": "Your plan covers one annual preventive visit with an in-network primary care doctor at no cost share when billed as preventive. Other services during the visit may be billed separately.",
        }

    # ---- dates and slots ----
    async def dates(self, call_id: str, text: str) -> dict[str, Any]:
        t = text.lower().strip()
        today = self.now.date()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
            return {"ok": True, "dates": [t]}
        # Recognize a spoken calendar date before considering a bare weekday.
        month_match = re.search(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b",
            t,
        )
        if month_match:
            try:
                year = int(month_match.group(3) or today.year)
                resolved = datetime.strptime(
                    f"{month_match.group(1)} {month_match.group(2)} {year}", "%B %d %Y"
                ).date()
                return {"ok": True, "dates": [resolved.isoformat()]}
            except ValueError:
                return {
                    "ok": False,
                    "error": "OUTSIDE_WINDOW",
                    "speak": "That date isn't valid. Which day would you like?",
                }
        if "tomorrow" in t:
            return {"ok": True, "dates": [(today + timedelta(days=1)).isoformat()]}
        for i, w in enumerate(WEEKDAYS):
            if w in t:
                first = self._next(i)
                if "next" in t:
                    first += timedelta(days=7)
                    return {"ok": True, "dates": [first.isoformat()]}
                if today.weekday() == i or (today.weekday() > i):
                    # Bare weekday late in the week: this coming one or the one after.
                    both = [first.isoformat(), (first + timedelta(days=7)).isoformat()]
                    return {
                        "ok": True,
                        "dates": both,
                        "ambiguous": True,
                        "speak": f"Do you mean {spoken(datetime.fromisoformat(both[0]).replace(tzinfo=ET)).split(' at ')[0]} or {spoken(datetime.fromisoformat(both[1]).replace(tzinfo=ET)).split(' at ')[0]}?",
                    }
                return {"ok": True, "dates": [first.isoformat()]}
        return {
            "ok": False,
            "error": "OUTSIDE_WINDOW",
            "speak": "Which day would you like?",
        }

    async def availability(
        self,
        call_id: str,
        provider_id: str,
        date_from: str,
        date_to: str,
        part_of_day: str,
    ) -> dict[str, Any]:
        c = self._c(call_id)
        d0, d1 = date.fromisoformat(date_from), date.fromisoformat(date_to)
        if d1 > self.now.date() + timedelta(days=14):
            return {
                "ok": False,
                "error": "OUTSIDE_WINDOW",
                "speak": "I can only look two weeks ahead.",
            }
        pod = part_of_day.strip().lower()
        found = [
            s
            for s in self.slots.values()
            if s["provider"] == provider_id
            and not s["booked"]
            and d0 <= s["start"].date() <= d1
            and s["start"] - self.now >= timedelta(hours=2)
            and (pod != "morning" or s["start"].hour < 12)
            and (pod != "afternoon" or s["start"].hour >= 12)
        ]
        found.sort(key=lambda s: s["start"])
        if not found:
            return {
                "ok": False,
                "error": "NO_AVAILABILITY",
                "speak": "I don't see an open time then.",
            }
        out = [{"slot_id": s["id"], "text": spoken(s["start"])} for s in found[:2]]
        c["offered"] = {o["slot_id"] for o in out}
        return {
            "ok": True,
            "slots": out,
            "speak": " or ".join(o["text"] for o in out) + "?",
        }

    async def slot(self, call_id: str, slot_id: str) -> dict[str, Any]:
        c = self._c(call_id)
        if slot_id not in c.get("offered", set()):
            return {
                "ok": False,
                "error": "UNKNOWN_PROVIDER",
                "speak": "That time wasn't one I offered. Let me check again.",
            }
        c["draft"] = {
            "slot": slot_id,
            "provider": self.slots[slot_id]["provider"],
            "token": None,
            "armed_seq": None,
            "armed_at": None,
        }
        return {"ok": True, "revision": 1}

    # ---- preview, armed, confirm ----
    def _hash(self, c: dict[str, Any]) -> str:
        d = c["draft"]
        return hashlib.sha256(
            f"{c['member']['name']}|{d['provider']}|{d['slot']}".encode()
        ).hexdigest()

    async def preview(self, call_id: str) -> dict[str, Any]:
        c = self._c(call_id)
        d = c.get("draft")
        if not d:
            return {
                "ok": False,
                "error": "STALE_CONFIRMATION",
                "speak": "Let's pick a time first.",
            }
        d["token"], d["hash"], d["armed_seq"], d["armed_at"] = (
            secrets.token_urlsafe(8),
            self._hash(c),
            None,
            None,
        )
        s = self.slots[d["slot"]]
        read_back = f"Just to confirm: {PROVIDERS[d['provider']]['name']}, {spoken(s['start'])}, as a new patient visit. Shall I book it?"
        return {"ok": True, "token": d["token"], "read_back": read_back}

    async def armed(self, call_id: str, token: str) -> dict[str, Any]:
        c = self._c(call_id)
        d = c.get("draft")
        if not d or d["token"] != token:
            return {
                "ok": False,
                "error": "STALE_CONFIRMATION",
                "speak": "That changed. Let me read it again.",
            }
        d["armed_seq"] = len(c["turns"])
        d["armed_at"] = datetime.now(ET)
        return {"ok": True, "armed_seq": d["armed_seq"]}

    async def confirm(self, call_id: str, token: str) -> dict[str, Any]:
        c = self._c(call_id)
        d = c.get("draft")
        if not d or d["token"] != token or d["hash"] != self._hash(c):
            return {
                "ok": False,
                "error": "STALE_CONFIRMATION",
                "speak": "That changed. Let me read it back again.",
            }
        if d["armed_seq"] is None:
            return {
                "ok": False,
                "error": "NOT_ARMED",
                "speak": "Let me read that back first.",
            }
        users = [t for t in c["turns"] if t["role"] == "user"]
        last = users[-1] if users else None
        if not last or last["seq"] <= d["armed_seq"]:
            return {
                "ok": False,
                "error": "NOT_CONFIRMED",
                "speak": "I need a yes from you first.",
            }
        if (
            not is_clear_yes(last["text"])
            or (datetime.now(ET) - d["armed_at"]).total_seconds() > YES_WINDOW_S
        ):
            return {
                "ok": False,
                "error": "NOT_CONFIRMED",
                "speak": "No problem, nothing is booked. Would you like to change anything?",
            }
        for a in self.appointments:
            if a["confirmation"] and a["token"] == token:
                return {
                    "ok": True,
                    "confirmation": a["confirmation"],
                    "speak": a["speak"],
                }
        s = self.slots[d["slot"]]
        if s["booked"] or s["start"] - self.now < timedelta(0):
            return {
                "ok": False,
                "error": "SLOT_TAKEN",
                "speak": "That time was just taken.",
            }
        for a in self.appointments:
            if (
                a["member"] == c["member"]["name"]
                and a["start"] < s["end"]
                and s["start"] < a["end"]
            ):
                return {
                    "ok": False,
                    "error": "OVERLAP",
                    "speak": "You already have an appointment at that time.",
                }
            if (
                a["provider"] == s["provider"]
                and a["start"] < s["end"]
                and s["start"] < a["end"]
            ):
                return {
                    "ok": False,
                    "error": "SLOT_TAKEN",
                    "speak": "That time was just taken.",
                }
        s["booked"] = True
        conf = f"MG-APT-{4800 + len(self.appointments) + 21}"
        spoken_conf = "M G A P T " + " ".join(
            conf.split("-")[-1]
        )  # spelled out for the voice
        speak = f"You're booked with {PROVIDERS[s['provider']]['name']} on {spoken(s['start'])}. Your confirmation number is {spoken_conf}. The office number is {PROVIDERS[s['provider']]['phone']}."
        self.appointments.append(
            {
                "confirmation": conf,
                "token": token,
                "member": c["member"]["name"],
                "provider": s["provider"],
                "start": s["start"],
                "end": s["end"],
                "speak": speak,
            }
        )
        return {"ok": True, "confirmation": conf, "speak": speak}

    async def followup(
        self, call_id: str, category: str, detail: str
    ) -> dict[str, Any]:
        ref = f"MG-{4821 + len(self.tasks)}"
        self.tasks.append({"reference": ref, "category": category, "detail": detail})
        return {
            "ok": True,
            "reference": ref,
            "speak": f"I've filed a request for our team. The reference is {ref}.",
        }

    async def appointment(self, call_id: str) -> dict[str, Any]:
        c = self._c(call_id)
        name = c["member"]["name"] if c["member"] else None
        mine = [
            {
                "confirmation": a["confirmation"],
                "token": a["token"],
                "when": spoken(a["start"]),
            }
            for a in self.appointments
            if a["member"] == name
        ]
        return {"ok": True, "appointments": mine}

    async def finalize(self, call_id: str) -> dict[str, Any]:
        return {
            "ok": True,
            "summary": {
                "appointments": len(self.appointments),
                "tasks": len(self.tasks),
            },
        }
