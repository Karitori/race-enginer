from models.strategy import StrategyInsight
from models.telemetry import TelemetryTick
from models.telemetry_packets import (
    PacketCarDamageData,
    PacketCarStatusData,
    PacketLapData,
    PacketSessionData,
)
from utils.telemetry_enums import (
    ERS_MODE_NAMES,
    FUEL_MIX_NAMES,
    SAFETY_CAR_NAMES,
    TYRE_COMPOUND_SHORT,
    WEATHER_NAMES,
)


def build_radio_context(
    telemetry: TelemetryTick | None,
    strategy: StrategyInsight | None,
    car_status: PacketCarStatusData | None,
    car_damage: PacketCarDamageData | None,
    session: PacketSessionData | None,
    lap_data: PacketLapData | None,
    player_idx: int,
) -> str:
    """Build a compact natural-language race context for LLM prompts."""
    parts: list[str] = []

    if telemetry:
        parts.append(
            f"Speed: {telemetry.speed:.0f}km/h, Gear: {telemetry.gear}, RPM: {telemetry.engine_rpm}"
        )
        parts.append(f"Lap: {telemetry.lap}, Sector: {telemetry.sector}")

    if car_status and player_idx < len(car_status.car_status_data):
        status = car_status.car_status_data[player_idx]
        compound = TYRE_COMPOUND_SHORT.get(status.visual_tyre_compound, "?")
        fuel_mix = FUEL_MIX_NAMES.get(status.fuel_mix, "?")
        ers_mode = ERS_MODE_NAMES.get(status.ers_deploy_mode, "?")
        ers_pct = status.ers_store_energy / 4000000.0 * 100
        parts.append(f"Tire: {compound} (Age: {status.tyres_age_laps} laps)")
        parts.append(
            f"Fuel: {status.fuel_remaining_laps:.1f} laps remaining (Mix: {fuel_mix})"
        )
        parts.append(f"ERS: {ers_pct:.0f}% ({ers_mode})")
        parts.append(f"DRS: {'Available' if status.drs_allowed else 'Not available'}")

    if car_damage and player_idx < len(car_damage.car_damage_data):
        damage = car_damage.car_damage_data[player_idx]
        parts.append(
            f"Tire Wear - FL:{damage.tyres_wear[2]:.1f}%, FR:{damage.tyres_wear[3]:.1f}%, "
            f"RL:{damage.tyres_wear[0]:.1f}%, RR:{damage.tyres_wear[1]:.1f}%"
        )
        damage_parts: list[str] = []
        if damage.front_left_wing_damage > 0:
            damage_parts.append(f"FL Wing:{damage.front_left_wing_damage}%")
        if damage.front_right_wing_damage > 0:
            damage_parts.append(f"FR Wing:{damage.front_right_wing_damage}%")
        if damage.rear_wing_damage > 0:
            damage_parts.append(f"Rear Wing:{damage.rear_wing_damage}%")
        if damage.floor_damage > 0:
            damage_parts.append(f"Floor:{damage.floor_damage}%")
        if damage.gear_box_damage > 0:
            damage_parts.append(f"Gearbox:{damage.gear_box_damage}%")
        if damage.engine_damage > 0:
            damage_parts.append(f"Engine:{damage.engine_damage}%")
        if damage_parts:
            parts.append(f"Damage: {', '.join(damage_parts)}")

    if lap_data and player_idx < len(lap_data.car_lap_data):
        lap = lap_data.car_lap_data[player_idx]
        parts.append(f"Position: P{lap.car_position}")
        if lap.delta_to_car_in_front_in_ms > 0:
            parts.append(f"Gap to front: {lap.delta_to_car_in_front_in_ms / 1000:.3f}s")
        if lap.last_lap_time_in_ms > 0:
            parts.append(f"Last Lap: {lap.last_lap_time_in_ms / 1000:.3f}s")
        parts.append(f"Pit Stops: {lap.num_pit_stops}")

    if session:
        weather = WEATHER_NAMES.get(session.weather, "Unknown")
        safety_car = SAFETY_CAR_NAMES.get(session.safety_car_status, "None")
        parts.append(
            f"Weather: {weather}, Track: {session.track_temperature}C, Air: {session.air_temperature}C"
        )
        if session.safety_car_status > 0:
            parts.append(f"Safety Car: {safety_car}")
        parts.append(f"Total Laps: {session.total_laps}")

    if strategy:
        parts.append(
            f"Strategy Team: {strategy.summary}. Rec: {strategy.recommendation}"
        )

    return ", ".join(parts) if parts else "No telemetry data available yet."

