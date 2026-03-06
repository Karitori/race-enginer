import asyncio

import pytest

from models.telemetry_packets import PacketEventData, PacketHeader, PacketSessionData
from services.event_bus_service import bus
from services.telemetry_state_service import SessionState


@pytest.mark.asyncio
async def test_session_state_publishes_race_session_changed_and_clears_transients():
    state = SessionState()
    changes: list[dict] = []

    async def on_change(payload: dict):
        changes.append(payload)

    bus.subscribe("race_session_changed", on_change)

    try:
        p1 = PacketSessionData(
            header=PacketHeader(session_uid=1001),
            session_type=5,
            track_id=5,
            total_laps=20,
        )
        p2 = PacketSessionData(
            header=PacketHeader(session_uid=1001),
            session_type=6,
            track_id=5,
            total_laps=24,
        )

        await bus.publish("packet_session", p1)
        await asyncio.sleep(0.01)
        assert state.session is not None
        assert not changes

        await bus.publish(
            "packet_event",
            PacketEventData(header=PacketHeader(session_uid=1001), event_string_code="SAFC"),
        )
        await asyncio.sleep(0.01)
        assert state.events_log

        await bus.publish("packet_session", p2)
        await asyncio.sleep(0.01)

        assert changes
        latest = changes[-1]
        assert tuple(latest["previous_signature"]) == (1001, 5, 5, 20)
        assert tuple(latest["new_signature"]) == (1001, 6, 5, 24)
        assert state.events_log == []
    finally:
        bus.unsubscribe("race_session_changed", on_change)
