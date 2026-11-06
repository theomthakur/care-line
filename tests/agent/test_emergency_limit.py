"""The 911 line is spoken once, reminded once, then the conversation moves on."""

from __future__ import annotations

import pytest
from livekit.agents import StopResponse, llm

import my_agent
from fake_backend import FakeBackend
from flow import Flow
from safety import EMERGENCY_LINE, EMERGENCY_REMINDER


class FakeSession:
    def __init__(self) -> None:
        self.said: list[str] = []

    async def say(self, text: str, **_: object) -> None:
        self.said.append(text)


@pytest.fixture
def agent(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("USE_FAKE_BACKEND", "1")
    a = my_agent.MyAgent()
    a.flow = Flow(FakeBackend())
    session = FakeSession()
    monkeypatch.setattr(my_agent.MyAgent, "session", property(lambda self: session))
    updates: list[str] = []

    async def fake_update(text: str) -> None:
        updates.append(text)

    monkeypatch.setattr(a, "update_instructions", fake_update)
    a.test_session, a.test_updates = session, updates  # type: ignore[attr-defined]
    return a


async def say(agent, text: str) -> bool:
    """True if the code answered itself, False if the turn goes on to the model."""
    await agent.flow.start("room")
    msg = llm.ChatMessage(role="user", content=[text])
    try:
        await agent.on_user_turn_completed(llm.ChatContext(), msg)
    except StopResponse:
        return True
    return False


@pytest.mark.asyncio
async def test_911_is_said_in_full_once_then_a_short_reminder_then_never_again(agent):
    s = agent.test_session
    assert await say(agent, "I think it is an emergency")
    assert s.said == [EMERGENCY_LINE]
    assert len(agent.test_updates) == 1 and "Do NOT repeat" in agent.test_updates[0]

    assert await say(agent, "this is a medical emergency, please help")
    assert s.said[-1] == EMERGENCY_REMINDER

    # Third and fourth time: the code stays quiet and the model carries on, gently.
    before = list(s.said)
    assert not await say(agent, "I need an ambulance")
    assert not await say(agent, "it is an emergency")
    assert s.said == before


@pytest.mark.asyncio
async def test_the_safety_task_is_filed_once(agent, monkeypatch):
    filed = []

    async def followup(category, detail):
        filed.append(category)
        return "ok"

    monkeypatch.setattr(agent.flow, "followup", followup)
    for text in ("I think it is an emergency", "it is an emergency", "ambulance now"):
        await say(agent, text)
    assert filed == ["safety"]
