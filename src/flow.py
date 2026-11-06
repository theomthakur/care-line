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


class Flow:
    def __init__(self, backend: Backend) -> None:
        self.backend = backend
        self.call_id: str | None = None
        self.verified = False
        self.provider_options: dict[str, str] = {}
        self.last_day = ""
        self.last_part = ""
        self.last_provider = ""
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
        res = await self.backend.start_call(room)
        self.call_id = res["call_id"]

    async def record_user_turn(self, text: str) -> None:
        """Awaited before any tool runs, so confirmation always reads the newest turn."""
        try:
            if not self.call_id:
                raise BackendUnavailableError("The call could not be started")
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
        self.provider_options = {p["id"]: p["name"] for p in res["providers"]}
        sel = await self._call(
            self.backend.select, self.call_id, res["providers"][0]["id"]
        )
        coverage = ""
        if isinstance(sel, dict) and sel.get("ok"):
            coverage = " " + sel["speak"]
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
        if d.get("ambiguous"):
            return line(
                d["speak"],
                "Ask which date, then call find_slots again with the exact date.",
            )
        dates = sorted(d["dates"])
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
        if not res.get("ok"):
            return line(
                res.get("speak", "I don't see an open time."),
                "If nothing works for the caller, offer a follow-up request.",
            )
        ids = ", ".join(f"{s['slot_id']} = {s['text']}" for s in res["slots"])
        return line(
            res["speak"],
            f"Slot ids for prepare_appointment: {ids}. Offer only these, as a choice.",
        )

    async def prepare(self, slot_id: str, say: Say) -> str | None:
        assert self.call_id
        self.token, self.armed = None, False
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
        if handle.interrupted:
            return (
                "NOT ARMED. The caller interrupted the read-back, so nothing can be confirmed yet. "
                "Respond to what they said. If they still want this time, call prepare_appointment again."
            )
        a = await self._call(self.backend.armed, self.call_id, self.token)
        if isinstance(a, str):
            return a
        if not a.get("ok"):
            return line(a.get("speak", "Let me read that again."))
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
        if res.get("ok"):
            self.booked = res["confirmation"]
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
            res = await self.backend.appointment(self.call_id)
        except BackendUnavailableError:
            res = {}
        for a in res.get("appointments", []):
            if a.get("token") == self.token:
                self.booked = a["confirmation"]
                return line(
                    f"Good news, it did go through. Your confirmation number is {a['confirmation']}."
                )
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
