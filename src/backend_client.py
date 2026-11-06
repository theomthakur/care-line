"""HTTP client for the MemberGuide backend (Aneesh and Siddhant's routes).

The agent has no database of its own. Every fact, rule and write lives behind these
calls, and the model never supplies a member id or a yes flag.

Every response is a dict with "ok": bool. A failed rule comes back as
{"ok": False, "error": CODE, "speak": "..."}. Only an unreachable or broken
backend raises BackendUnavailableError.

Route shapes follow docs/MEMBERGUIDE-FINAL-PLAN.md section 8. The exact field names
are agreed in contracts/ at 4:00. If a name changes there, change it here only.
"""

from __future__ import annotations

import calendar
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

import aiohttp

TIMEOUT_S = 6.0


class BackendUnavailableError(Exception):
    """The backend could not be reached, or answered something unreadable."""


class Backend(Protocol):
    async def start_call(self, room: str) -> dict[str, Any]: ...
    async def verify(
        self, call_id: str, digits: str, birth_month: str
    ) -> dict[str, Any]: ...
    async def turn(self, call_id: str, role: str, text: str) -> dict[str, Any]: ...
    async def providers(
        self, call_id: str, specialty: str, zip_code: str
    ) -> dict[str, Any]: ...
    async def select(self, call_id: str, provider_id: str) -> dict[str, Any]: ...
    async def dates(self, call_id: str, text: str) -> dict[str, Any]: ...
    async def availability(
        self,
        call_id: str,
        provider_id: str,
        date_from: str,
        date_to: str,
        part_of_day: str,
    ) -> dict[str, Any]: ...
    async def slot(self, call_id: str, slot_id: str) -> dict[str, Any]: ...
    async def preview(self, call_id: str) -> dict[str, Any]: ...
    async def armed(self, call_id: str, token: str) -> dict[str, Any]: ...
    async def confirm(self, call_id: str, token: str) -> dict[str, Any]: ...
    async def followup(
        self, call_id: str, category: str, detail: str
    ) -> dict[str, Any]: ...
    async def appointment(self, call_id: str) -> dict[str, Any]: ...
    async def finalize(self, call_id: str) -> dict[str, Any]: ...


class HttpBackend:
    def __init__(
        self, base_url: str | None = None, agent_key: str | None = None
    ) -> None:
        self.base_url = (
            base_url or os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
        ).rstrip("/")
        key = (
            agent_key
            if agent_key is not None
            else os.getenv("MEMBERGUIDE_AGENT_KEY", "")
        )
        if not key:
            raise BackendUnavailableError("MEMBERGUIDE_AGENT_KEY is required")
        self._headers = {"X-Agent-Key": key}
        self._session: aiohttp.ClientSession | None = None

    def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=self._headers, timeout=aiohttp.ClientTimeout(total=TIMEOUT_S)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _post(
        self, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            async with self._http().post(self.base_url + path, json=body or {}) as r:
                data = await r.json(content_type=None)
                status = r.status
        except (aiohttp.ClientError, TimeoutError, ValueError) as e:
            raise BackendUnavailableError(f"{path}: {e}") from e
        if not isinstance(data, dict):
            raise BackendUnavailableError(f"{path}: unreadable response")
        if status >= 400:
            if (
                400 <= status < 500
                and isinstance(data.get("error"), str)
                and data.get("speak")
            ):
                data["ok"] = False
                return data
            raise BackendUnavailableError(f"{path}: HTTP {status}")
        data.setdefault("ok", "error" not in data)
        return data

    async def _get(self, path: str) -> dict[str, Any]:
        try:
            async with self._http().get(self.base_url + path) as r:
                data = await r.json(content_type=None)
                status = r.status
        except (aiohttp.ClientError, TimeoutError, ValueError) as e:
            raise BackendUnavailableError(f"{path}: {e}") from e
        if not isinstance(data, dict):
            raise BackendUnavailableError(f"{path}: unreadable response")
        if status >= 400:
            if (
                400 <= status < 500
                and isinstance(data.get("error"), str)
                and data.get("speak")
            ):
                data["ok"] = False
                return data
            raise BackendUnavailableError(f"{path}: HTTP {status}")
        data.setdefault("ok", "error" not in data)
        return data

    async def start_call(self, room: str) -> dict[str, Any]:
        return await self._post("/calls", {"room": room})

    async def verify(
        self, call_id: str, digits: str, birth_month: str
    ) -> dict[str, Any]:
        value = str(birth_month).strip().lower()
        months = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
        months.update(
            {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}
        )
        month = int(value) if value.isdigit() else months.get(value)
        if month not in range(1, 13):
            return {
                "ok": False,
                "error": "INVALID_REQUEST",
                "speak": "Please tell me your birth month again.",
            }
        return await self._post(
            f"/calls/{call_id}/verify",
            {"member_digits": digits, "birth_month": month},
        )

    async def turn(self, call_id: str, role: str, text: str) -> dict[str, Any]:
        payload = {"client_turn_id": uuid4().hex, "role": role, "text": text}
        try:
            return await self._post(f"/calls/{call_id}/turn", payload)
        except BackendUnavailableError:
            # The first write may have committed; retry with the SAME delivery ID.
            return await self._post(f"/calls/{call_id}/turn", payload)

    async def providers(
        self, call_id: str, specialty: str, zip_code: str
    ) -> dict[str, Any]:
        return await self._post(
            f"/calls/{call_id}/providers", {"specialty": specialty, "zip": zip_code}
        )

    async def select(self, call_id: str, provider_id: str) -> dict[str, Any]:
        return await self._post(
            f"/calls/{call_id}/select", {"provider_id": provider_id}
        )

    async def dates(self, call_id: str, text: str) -> dict[str, Any]:
        text = text.strip().lower()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            try:
                date.fromisoformat(text)
            except ValueError:
                return {
                    "ok": False,
                    "speak": "That date is invalid. Please choose another day.",
                }
            return {
                "ok": True,
                "candidates": [{"date": text}],
                "needs_clarification": False,
            }
        now = await self._get("/now")
        today = date.fromisoformat(now["business_date"])
        if re.search(
            r"\b(?:earliest|soonest|next available|first available|upcoming|any available|first opening)\b",
            text,
        ):
            return {
                "ok": True,
                "candidates": [
                    {"date": today.isoformat()},
                    {"date": (today + timedelta(days=14)).isoformat()},
                ],
                "needs_clarification": False,
            }
        match = re.search(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b",
            text,
        )
        if match:
            try:
                value = (
                    datetime.strptime(
                        f"{match.group(1)} {match.group(2)} {match.group(3) or today.year}",
                        "%B %d %Y",
                    )
                    .date()
                    .isoformat()
                )
            except ValueError:
                return {
                    "ok": False,
                    "speak": "That date is invalid. Please choose another day.",
                }
            return {
                "ok": True,
                "candidates": [{"date": value}],
                "needs_clarification": False,
            }
        word = next(
            (
                w
                for w in (
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                    "sunday",
                    "today",
                    "tomorrow",
                )
                if re.search(r"\b" + w + r"\b", text)
            ),
            None,
        )
        if not word:
            return {"ok": False, "speak": "Which day would you like?"}
        which = (
            "next"
            if re.search(r"\bnext\b", text)
            else "this"
            if re.search(r"\bthis\b", text)
            else "unspecified"
        )
        if word in ("today", "tomorrow"):
            which = "unspecified"
        return await self._post(
            f"/calls/{call_id}/dates", {"weekday": word, "which": which}
        )

    async def availability(
        self,
        call_id: str,
        provider_id: str,
        date_from: str,
        date_to: str,
        part_of_day: str,
    ) -> dict[str, Any]:
        return await self._post(
            f"/calls/{call_id}/availability",
            {
                "date_from": date_from,
                "date_to": date_to,
                "part_of_day": part_of_day or "any",
            },
        )

    async def slot(self, call_id: str, slot_id: str) -> dict[str, Any]:
        return await self._post(f"/calls/{call_id}/slot", {"slot_id": slot_id})

    async def preview(self, call_id: str) -> dict[str, Any]:
        return await self._post(f"/calls/{call_id}/appointment/preview")

    async def armed(self, call_id: str, token: str) -> dict[str, Any]:
        return await self._post(f"/calls/{call_id}/appointment/armed", {"token": token})

    async def confirm(self, call_id: str, token: str) -> dict[str, Any]:
        return await self._post(
            f"/calls/{call_id}/appointment/confirm", {"token": token}
        )

    async def followup(
        self, call_id: str, category: str, detail: str
    ) -> dict[str, Any]:
        return await self._post(
            f"/calls/{call_id}/followup", {"category": category, "detail": detail}
        )

    async def appointment(self, call_id: str) -> dict[str, Any]:
        return await self._get(f"/calls/{call_id}/appointment")

    async def finalize(self, call_id: str) -> dict[str, Any]:
        return await self._post(f"/calls/{call_id}/finalize")


def make_backend() -> Backend:
    """The real backend, or the stand-in while USE_FAKE_BACKEND=1 (off by 6:00)."""
    if os.getenv("USE_FAKE_BACKEND", "0").strip() in {"1", "true", "yes"}:
        from fake_backend import FakeBackend

        return FakeBackend()
    return HttpBackend()
