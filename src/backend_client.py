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

import os
from typing import Any, Protocol

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
        self._headers = {
            "X-Agent-Key": agent_key or os.getenv("AGENT_KEY", "dev-agent-key")
        }
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
        return await self._post(
            f"/calls/{call_id}/verify",
            {"member_digits": digits, "birth_month": birth_month},
        )

    async def turn(self, call_id: str, role: str, text: str) -> dict[str, Any]:
        return await self._post(f"/calls/{call_id}/turn", {"role": role, "text": text})

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
        return await self._post(f"/calls/{call_id}/dates", {"text": text})

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
                "provider_id": provider_id,
                "date_from": date_from,
                "date_to": date_to,
                "part_of_day": part_of_day,
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
