import asyncio
import pytest
from services.event_bus_service import bus
from services.feedback_service import PerformanceAnalyzer
from models.telemetry import TelemetryTick, DrivingInsight
from models.telemetry_packets import (
    CarLapData,
    CarStatus,
    PacketCarStatusData,
    PacketHeader,
    PacketLapData,
)


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


@pytest.mark.asyncio
async def test_analyzer_calls_attack_when_drs_and_gap_is_close(analyzer):
    insights = []

    async def insight_handler(data: DrivingInsight):
        insights.append(data)

    bus.subscribe("driving_insight", insight_handler)

    header = PacketHeader(player_car_index=0)
    lap_packet = PacketLapData(
        header=header,
        car_lap_data=[
            CarLapData(
                car_position=6,
                current_lap_num=4,
                delta_to_car_in_front_in_ms=650,
                pit_status=0,
            )
        ],
    )
    status_packet = PacketCarStatusData(
        header=header,
        car_status_data=[
            CarStatus(
                drs_allowed=1,
                ers_store_energy=2400000.0,
            )
        ],
    )

    await analyzer._handle_lap_data(lap_packet)
    await analyzer._handle_car_status(status_packet)
    await asyncio.sleep(0.01)

    assert any("DRS is available." in i.message for i in insights)
    assert any("Use overtake now." in i.message for i in insights)


@pytest.mark.asyncio
async def test_analyzer_calls_prep_drs_when_close_without_drs(analyzer):
    insights = []

    async def insight_handler(data: DrivingInsight):
        insights.append(data)

    bus.subscribe("driving_insight", insight_handler)

    header = PacketHeader(player_car_index=0)
    lap_packet = PacketLapData(
        header=header,
        car_lap_data=[
            CarLapData(
                car_position=7,
                current_lap_num=5,
                delta_to_car_in_front_in_ms=500,
                pit_status=0,
            )
        ],
    )
    status_packet = PacketCarStatusData(
        header=header,
        car_status_data=[CarStatus(drs_allowed=0)],
    )

    await analyzer._handle_lap_data(lap_packet)
    await analyzer._handle_car_status(status_packet)
    await asyncio.sleep(0.01)

    assert any("prep DRS for the next zone" in i.message for i in insights)


@pytest.mark.asyncio
async def test_analyzer_attack_call_respects_cooldown(analyzer):
    insights = []

    async def insight_handler(data: DrivingInsight):
        insights.append(data)

    bus.subscribe("driving_insight", insight_handler)

    header = PacketHeader(player_car_index=0)
    lap_packet = PacketLapData(
        header=header,
        car_lap_data=[
            CarLapData(
                car_position=5,
                current_lap_num=6,
                delta_to_car_in_front_in_ms=700,
                pit_status=0,
            )
        ],
    )
    status_packet = PacketCarStatusData(
        header=header,
        car_status_data=[CarStatus(drs_allowed=1, ers_store_energy=2600000.0)],
    )

    await analyzer._handle_lap_data(lap_packet)
    await analyzer._handle_car_status(status_packet)
    await asyncio.sleep(0.01)

    analyzer._last_position_check_time = 0.0
    analyzer._last_car_status_time = 0.0
    await analyzer._handle_lap_data(lap_packet)
    await analyzer._handle_car_status(status_packet)
    await asyncio.sleep(0.01)

    drs_attack_calls = [i for i in insights if "DRS is available." in i.message]
    assert len(drs_attack_calls) == 1
