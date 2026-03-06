import pytest

from agents.race_engineer_agent import RaceEngineerAgent


class _StubTelemetryProvider:
    def get_gap_snapshot(self):
        return {
            "available": True,
            "lap": 4,
            "position": 6,
            "gap_front_ms": 1200,
            "gap_leader_ms": 8400,
        }

    def get_car_state_snapshot(self):
        return {
            "available": True,
            "fuel_remaining_laps": 6.4,
            "ers_pct": 42.0,
            "drs_available": True,
            "tyre_age_laps": 11,
            "compound": "M",
        }

    def get_health_snapshot(self):
        return {
            "available": True,
            "max_brake_temp_c": 910,
            "max_tire_surface_temp_c": 116,
            "max_damage_component": "front_left_wing",
            "max_damage_pct": 18,
        }


@pytest.mark.asyncio
async def test_race_engineer_agent_answers_gap_from_tool(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    agent = RaceEngineerAgent(
        telemetry_provider=_StubTelemetryProvider(),
        thread_id="test-gap-thread",
    )
    reply = await agent.answer(
        query="Rebecca, what's my gap to the leader?",
        telemetry_context="lap=4 position=6",
        persona_name="focused teammate",
        persona_instruction="Persona text.",
        tone_instruction="Tone text.",
        driver_preference_instruction="Driver preference text.",
    )
    text = reply.radio_text.lower()
    assert "leader" in text
    assert "p6" in text
    assert "driver latest message" not in text


@pytest.mark.asyncio
async def test_race_engineer_agent_answers_car_state_from_tool(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    agent = RaceEngineerAgent(
        telemetry_provider=_StubTelemetryProvider(),
        thread_id="test-state-thread",
    )
    reply = await agent.answer(
        query="Fuel and ERS status?",
        telemetry_context="fuel/ers sample",
        persona_name="focused teammate",
        persona_instruction="Persona text.",
        tone_instruction="Tone text.",
        driver_preference_instruction="Driver preference text.",
    )
    text = reply.radio_text.lower()
    assert "fuel" in text
    assert "ers" in text
