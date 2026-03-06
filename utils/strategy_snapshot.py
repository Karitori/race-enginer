from typing import Any

from db.contracts import TelemetryRepository
from utils.collections import first_or_none


def collect_strategy_snapshot(repository: TelemetryRepository) -> dict[str, Any]:
    """Collects a compact telemetry snapshot for strategy analysis."""
    snapshot: dict[str, Any] = {}

    wear = repository.query(
        """
        SELECT tyres_wear_fl, tyres_wear_fr, tyres_wear_rl, tyres_wear_rr
        FROM car_damage WHERE car_index = 0
        ORDER BY timestamp DESC LIMIT 1
        """
    )
    fuel = repository.query(
        """
        SELECT fuel_in_tank, fuel_remaining_laps, actual_tyre_compound, tyres_age_laps
        FROM car_status WHERE car_index = 0
        ORDER BY timestamp DESC LIMIT 1
        """
    )
    lap = repository.query(
        """
        SELECT car_position, delta_to_car_in_front_in_ms, delta_to_race_leader_in_ms,
               current_lap_num, num_pit_stops
        FROM lap_data WHERE car_index = 0
        ORDER BY timestamp DESC LIMIT 1
        """
    )
    weather = repository.query(
        """
        SELECT weather, track_temperature, air_temperature, rain_percentage,
               pit_stop_window_ideal_lap, pit_stop_window_latest_lap
        FROM session_data ORDER BY timestamp DESC LIMIT 1
        """
    )

    snapshot["tire_wear"] = first_or_none(wear)
    snapshot["fuel"] = first_or_none(fuel)
    snapshot["lap"] = first_or_none(lap)
    snapshot["weather"] = first_or_none(weather)
    return snapshot



