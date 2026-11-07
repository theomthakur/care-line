"""The production model receives a status check, never a demographic form."""

from livekit.agents import llm

import my_agent


def test_production_tool_schema_cannot_collect_identity_answers(monkeypatch):
    monkeypatch.setenv("MEMBERGUIDE_ENV", "production")
    monkeypatch.setattr(my_agent, "make_backend", lambda: object())
    agent = my_agent.MyAgent()
    tools = {tool.id: tool for tool in agent.tools}
    assert "verify_demo_member" not in tools
    assert "end_call" in tools
    schema = llm.utils.build_strict_openai_schema(tools["check_patient_identity"])
    assert schema["function"]["parameters"]["properties"] == {}


def test_synthetic_tool_remains_explicitly_separate(monkeypatch):
    monkeypatch.setenv("MEMBERGUIDE_ENV", "synthetic")
    monkeypatch.setattr(my_agent, "make_backend", lambda: object())
    tools = {tool.id for tool in my_agent.MyAgent().tools}
    assert "verify_demo_member" in tools and "check_patient_identity" not in tools
