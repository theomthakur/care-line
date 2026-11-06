"""The six tools' logic, apart from LiveKit so it can be tested without a call.

Each method returns the text the model sees, or None when nothing more should be said
(the code already spoke). The model never gets a member id or a yes flag. Every
success line comes from the backend's `speak`, so "booked" is only ever said after
the backend says so.

Spec: docs/MEMBERGUIDE-FINAL-PLAN.md sections 7 and 8.
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from backend_client import Backend, BackendUnavailableError

logger = logging.getLogger("flow")

DOWN = (
    "I'm having trouble reaching our system right now. Tell the caller that plainly, "
    "do not say anything was booked or saved, and offer to try once more."
)
DOWN_TWICE = (
    "Our system is still not responding. Tell the caller you can't finish this on the "
    "call, apologize briefly, ask them to call back in a few minutes, and say goodbye."
)


class SpeechLike(Protocol):
    interrupted: bool

    def wait_for_playout(self) -> Awaitable[Any]: ...


Say = Callable[[str], SpeechLike]


def line(speak: str, note: str = "") -> str:
    out = f"Say this, nearly as written: {speak}"
    return f"{out}\nNotes for you, never read these out: {note}" if note else out


_NUMBER_WORDS = {
    "zero": "0",
    "oh": "0",
    "o": "0",
    "one": "1",
    "two": "2",
    "to": "2",
    "too": "2",
    "three": "3",
    "four": "4",
    "for": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}


def spoken_digits(value: str) -> str:
    """'four four one seven', '4-4-1-7' and '4417' all become '4417'. Nothing is guessed."""
    out = []
    for piece in re.split(r"[^A-Za-z0-9]+", str(value).strip().lower()):
        if piece.isdigit():
            out.append(piece)
        elif piece in _NUMBER_WORDS:
            out.append(_NUMBER_WORDS[piece])
        elif piece:
            return ""  # a word that is not a digit: treat the whole thing as unclear
    return "".join(out)


class Flow:
    def __init__(self, backend: Backend) -> None:
        self.backend = backend
        self.call_id: str | None = None
        self.room = ""
        self.verified = False
        self.provider_options: dict[str, str] = {}
        self.last_day = ""
        self.last_part = ""
        self.last_provider = ""
        self.offered: set[str] = set()  # slot ids from the latest availability
        self.token: str | None = None
        self.armed = False
        self.booked: str | None = None
        self.failures = 0

    # ---- plumbing ----
    async def _call(
        self, fn: Callable[..., Awaitable[dict[str, Any]]], *a: Any
    ) -> dict[str, Any] | str:
        """Run one backend call. An outage becomes text for the model, never a success."""
        try:
            res = await fn(*a)
        except BackendUnavailableError as e:
            self.failures += 1
            logger.warning("backend unavailable: %s", e)
            return DOWN_TWICE if self.failures >= 2 else DOWN
        self.failures = 0
        return res

    async def start(self, room: str) -> None:
        self.room = room
        res = await self.backend.start_call(room)
        self.call_id = res["call_id"]

    async def record_user_turn(self, text: str) -> None:
        """Awaited before any tool runs, so confirmation always reads the newest turn."""
        try:
            if not self.call_id:  # the backend was down at pickup: try again now
                await self.start(self.room)
            result = await self.backend.turn(self.call_id, "user", text)
            if not result.get("ok"):
                raise BackendUnavailableError("The caller's turn could not be saved")
        except BackendUnavailableError:
            self.token, self.armed = None, False
            raise

    async def record_assistant_turn(self, text: str) -> None:
        if self.call_id:
            with contextlib.suppress(BackendUnavailableError):
                await self.backend.turn(self.call_id, "assistant", text)

    async def finalize(self) -> None:
        if self.call_id:
            try:
                await self.backend.finalize(self.call_id)
            except BackendUnavailableError as e:
                logger.warning("finalize failed: %s", e)

    # ---- tools ----
    async def verify(self, digits: str, birth_month: str) -> str:
        assert self.call_id
        digits = spoken_digits(digits)
        if len(digits) != 4:
            # A mumbled number is not a wrong number: don't spend one of three tries.
            return (
                "UNCLEAR. You did not get exactly four digits. Do not guess and do not "
                "verify. Ask the caller to say the last four digits of their member number "
                "slowly, one at a time."
            )
        res = await self._call(self.backend.verify, self.call_id, digits, birth_month)
        if isinstance(res, str):
            return res
        self.verified = bool(res.get("ok"))
        if not res.get("ok"):
            return line(
                res.get("speak", "I couldn't verify that."),
                "Do not say which part was wrong.",
            )
        return line(res["speak"], "Now ask what kind of doctor and the ZIP code.")

    async def find_providers(self, specialty: str, zip_code: str) -> str:
        assert self.call_id
        res = await self._call(
            self.backend.providers, self.call_id, specialty, zip_code
        )
        if isinstance(res, str):
            return res
        if not res.get("ok"):
            return line(res.get("speak", "I couldn't find a match."))
        if not res.get("providers"):
            return line(res.get("speak", "I couldn't find a doctor that matches."))
        self.provider_options = {p["id"]: p["name"] for p in res["providers"]}
        coverage = ""
        why = "; ".join(f"{e['name']}: {e['reason']}" for e in res.get("excluded", []))
        ids = ", ".join(
            f"{pid} = {name}" for pid, name in self.provider_options.items()
        )
        note = f"Doctor ids for find_slots: {ids}."
        if why:
            note += f" Doctors you cannot offer, and why: {why}. Say why only if asked or if the caller names one."
        return line(
            res["speak"] + coverage, note + " Then ask which doctor they prefer."
        )

    async def find_slots(
        self, provider_id: str, day: str, part_of_day: str = ""
    ) -> str:
        assert self.call_id
        if provider_id not in self.provider_options:
            ids = (
                ", ".join(f"{k} = {v}" for k, v in self.provider_options.items())
                or "none yet"
            )
            return f"Unknown doctor id. Use one of: {ids}. Search for doctors first if there are none."
        selected = await self._call(self.backend.select, self.call_id, provider_id)
        if isinstance(selected, str):
            return selected
        if not selected.get("ok"):
            return line(selected.get("speak", "I couldn't select that doctor."))
        d = await self._call(self.backend.dates, self.call_id, day)
        if isinstance(d, str):
            return d
        if not d.get("ok"):
            return line(d.get("speak", "Which day would you like?"))
        if d.get("needs_clarification") or d.get("ambiguous"):
            return line(
                d["speak"],
                "Ask which date, then call find_slots again with the exact date.",
            )
        dates = sorted(d.get("dates") or [c["date"] for c in d.get("candidates", [])])
        if not dates:
            return line(d.get("speak", "Which day would you like?"))
        self.last_day, self.last_part, self.last_provider = (
            day,
            part_of_day,
            provider_id,
        )
        res = await self._call(
            self.backend.availability,
            self.call_id,
            provider_id,
            dates[0],
            dates[-1],
            part_of_day,
        )
        if isinstance(res, str):
            return res
        if not res.get("ok") and res.get("error") == "NO_AVAILABILITY":
            # Offer genuine alternatives from the same provider and preferences;
            # never infer availability from the fixture calendar.
            window = await self._call(
                self.backend.dates, self.call_id, "earliest available"
            )
            bounds = (
                sorted(
                    window.get("dates")
                    or [c["date"] for c in window.get("candidates", [])]
                )
                if isinstance(window, dict) and window.get("ok")
                else []
            )
            if bounds:
                alt = await self._call(
                    self.backend.availability,
                    self.call_id,
                    provider_id,
                    bounds[0],
                    bounds[-1],
                    part_of_day,
                )
                if isinstance(alt, dict) and alt.get("ok") and alt.get("slots"):
                    ids = ", ".join(
                        f"{slot['slot_id']} = {slot['text']}" for slot in alt["slots"]
                    )
                    return line(
                        "I don't see an opening for that day. The next available options are "
                        + alt["speak"],
                        f"Slot ids for prepare_appointment: {ids}. Offer only these, as a choice.",
                    )
        if not res.get("ok"):
            return line(
                res.get("speak", "I don't see an open time."),
                "If nothing works for the caller, offer a follow-up request.",
            )
        self.offered = {s["slot_id"] for s in res["slots"]}
        ids = ", ".join(f"{s['slot_id']} = {s['text']}" for s in res["slots"])
        return line(
            res["speak"],
            f"Slot ids for prepare_appointment: {ids}. Offer only these, as a choice.",
        )

    async def _recover_slot(self, slot_id: str) -> str | None:
        """The model picked a time from a doctor it checked earlier. Checking another doctor
        replaced the offered list, so look that doctor up again for that date. Returns text
        for the model only if the time is gone."""
        m = re.fullmatch(r"S-(P\d+)-(\d{4})(\d{2})(\d{2})-\d{4}", slot_id)
        if not m or m.group(1) not in self.provider_options:
            return None
        day = f"{m.group(2)}-{m.group(3)}-{m.group(4)}"
        out = await self.find_slots(m.group(1), day)
        if slot_id in self.offered:
            return None
        return (
            "That exact time is not open any more. Do not say the doctor is unavailable on "
            "other days. Offer the times below.\n" + out
        )

    async def prepare(
        self, slot_id: str, say: Say, interrupted: Callable[[], bool] | None = None
    ) -> str | None:
        assert self.call_id
        self.token, self.armed = None, False
        if slot_id not in self.offered:
            lost = await self._recover_slot(slot_id)
            if lost:
                return lost
        s = await self._call(self.backend.slot, self.call_id, slot_id)
        if isinstance(s, str):
            return s
        if not s.get("ok"):
            return line(s.get("speak", "Let me check that time again."))
        p = await self._call(self.backend.preview, self.call_id)
        if isinstance(p, str):
            return p
        if not p.get("ok"):
            return line(p.get("speak", "Let's pick a time again."))
        self.token = p["token"]
        handle = say(p["read_back"])
        await handle.wait_for_playout()
        if handle.interrupted or (interrupted is not None and interrupted()):
            return (
                "NOT ARMED. The caller interrupted the read-back, so nothing can be confirmed yet. "
                "Respond to what they said. If they still want this time, call prepare_appointment again."
            )
        a = await self._call(self.backend.armed, self.call_id, self.token)
        if isinstance(a, str):
            return a
        if not a.get("ok"):
            return line(a.get("speak", "Let me read that again."))
        if interrupted is not None and interrupted():
            self.token, self.armed = None, False
            return (
                "NOT ARMED. The caller interrupted the read-back. Read it back again."
            )
        self.armed = True
        return None  # The read-back already asked the question. Wait for the caller.

    async def confirm(self) -> str:
        assert self.call_id
        if not self.token or not self.armed:
            return "NOT ARMED. Nothing is booked. Call prepare_appointment first and wait for the caller's yes."
        res = await self._call(self.backend.confirm, self.call_id, self.token)
        if isinstance(res, str):
            return await self._unknown_outcome()
        return await self._after_confirm(res)

    async def _after_confirm(self, res: dict[str, Any]) -> str:
        confirmation = (res.get("appointment") or {}).get("confirmation") or res.get(
            "confirmation"
        )
        if res.get("ok") and not (confirmation and res.get("speak")):
            return await self._unknown_outcome()  # a success we cannot read is not one
        if res.get("ok"):
            self.booked = confirmation
            return line(
                res["speak"], "Then ask if there is anything else, and say goodbye."
            )
        err = res.get("error", "")
        if err == "SLOT_TAKEN":
            self.armed = False
            alt = await self.find_slots(
                self.last_provider, self.last_day, self.last_part
            )
            return f"{line(res.get('speak', 'That time was just taken.'))}\nNothing is booked.\n{alt}"
        self.armed = err not in {"STALE_CONFIRMATION", "OVERLAP"} and self.armed
        return line(
            res.get("speak", "I couldn't book that."),
            "Nothing is booked. Never say it is.",
        )

    async def _unknown_outcome(self) -> str:
        """The confirm call failed. The booking may or may not exist: look before claiming anything."""
        assert self.call_id
        try:
            # Idempotent replay is keyed to this call and the original token.
            res = await self.backend.confirm(self.call_id, self.token)
            appointment = res.get("appointment") or {}
            confirmation = appointment.get("confirmation") or res.get("confirmation")
            if res.get("ok") and confirmation and res.get("speak"):
                self.booked = confirmation
                return line(res["speak"])
        except BackendUnavailableError:
            pass
        try:
            saved = await self.backend.appointment(self.call_id)
            appointments = saved.get("appointments", [])
            # Core scopes this endpoint to the current call and permits one booking.
            if (
                saved.get("ok")
                and len(appointments) == 1
                and appointments[0].get("confirmation")
            ):
                confirmation = appointments[0]["confirmation"]
                spoken = saved.get("speak")
                # The legacy fake response includes tokens; match it explicitly.
                if spoken or appointments[0].get("token") == self.token:
                    self.booked = confirmation
                    return line(
                        spoken
                        or f"Good news, it did go through. Your confirmation number is {confirmation}."
                    )
        except BackendUnavailableError:
            pass
        return (
            "UNKNOWN OUTCOME. Our system did not confirm the booking, so do not say it is booked. "
            "Tell the caller we could not confirm it, and offer a follow-up request or to try again."
        )

    async def followup(self, category: str, detail: str) -> str:
        assert self.call_id
        res = await self._call(self.backend.followup, self.call_id, category, detail)
        if isinstance(res, str):
            return res
        return line(
            res.get("speak", "I've filed a request for our team."),
            "Then ask if there is anything else.",
        )
