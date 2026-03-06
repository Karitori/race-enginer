import asyncio
import pytest
from services.event_bus_service import bus
from services.feedback_service import PerformanceAnalyzer
from models.telemetry import TelemetryTick, DrivingInsight


@pytest.fixture
def analyzer():
    # Instantiating sets up the subscriptions
    return PerformanceAnalyzer()


@pytest.mark.asyncio
async def test_analyzer_detects_new_lap(analyzer):
    insights = []

    async def insight_handler(data: DrivingInsight):
        insights.append(data)

    bus.subscribe("driving_insight", insight_handler)

    tick = TelemetryTick(
        speed=100.0,
        gear=2,
        throttle=1.0,
        brake=0.0,
        steering=0.0,
        engine_rpm=5000,
        tire_wear_fl=5.0,
        tire_wear_fr=5.0,
        tire_wear_rl=5.0,
        tire_wear_rr=5.0,
        lap=2,  # Triggers new lap
        track_position=0.0,
        sector=1,
    )

    await bus.publish("telemetry_tick", tick)
    await asyncio.sleep(0.01)

    assert len(insights) > 0
    assert any("Lap 2" in i.message for i in insights)


@pytest.mark.asyncio
async def test_analyzer_detects_high_tire_wear(analyzer):
    insights = []

    async def insight_handler(data: DrivingInsight):
        insights.append(data)

    bus.subscribe("driving_insight", insight_handler)

    tick = TelemetryTick(
        speed=100.0,
        gear=2,
        throttle=1.0,
        brake=0.0,
        steering=0.0,
        engine_rpm=5000,
        tire_wear_fl=65.0,  # Triggers tire wear warning
        tire_wear_fr=5.0,
        tire_wear_rl=5.0,
        tire_wear_rr=5.0,
        lap=2,
        track_position=0.0,
        sector=1,
    )

    # Must wait slightly for async handlers to finish
    await bus.publish("telemetry_tick", tick)
    await asyncio.sleep(0.01)

    assert any(
        i.type == "strategy" and "Tires are heavily worn" in i.message for i in insights
    )


@pytest.mark.asyncio
async def test_analyzer_lockup_warning_has_cooldown(analyzer):
    insights = []

    async def insight_handler(data: DrivingInsight):
        insights.append(data)

    bus.subscribe("driving_insight", insight_handler)

    hard_brake_tick = TelemetryTick(
        speed=300.0,
        gear=7,
        throttle=0.0,
        brake=0.95,
        steering=0.0,
        engine_rpm=11000,
        tire_wear_fl=5.0,
        tire_wear_fr=5.0,
        tire_wear_rl=5.0,
        tire_wear_rr=5.0,
        lap=1,
        track_position=0.5,
        sector=2,
    )
    release_tick = TelemetryTick(
        speed=290.0,
        gear=7,
        throttle=0.3,
        brake=0.0,
        steering=0.0,
        engine_rpm=10000,
        tire_wear_fl=5.0,
        tire_wear_fr=5.0,
        tire_wear_rl=5.0,
        tire_wear_rr=5.0,
        lap=1,
        track_position=0.55,
        sector=2,
    )

    await analyzer._handle_telemetry_tick(hard_brake_tick)
    await analyzer._handle_telemetry_tick(release_tick)
    await analyzer._handle_telemetry_tick(hard_brake_tick)
    await asyncio.sleep(0.01)

    lockup_related = [
        i for i in insights if "brake entry" in i.message.lower() or "lockup" in i.message.lower()
    ]
    assert len(lockup_related) == 1
