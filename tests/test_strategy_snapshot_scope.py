from datetime import timedelta

from db.telemetry_repository import DuckDBTelemetryRepository
from utils.strategy_snapshot import collect_strategy_snapshot


def _timestamp_literal(value) -> str:
    text = str(value).replace("T", " ").replace("'", "''")
    return f"TIMESTAMP '{text}'"


def test_collect_strategy_snapshot_ignores_previous_run_rows():
    repo = DuckDBTelemetryRepository(":memory:")
    try:
        run_started_at = repo.query(
            "SELECT started_at FROM app_runs ORDER BY started_at DESC LIMIT 1"
        )[0][0]
        stale_ts = _timestamp_literal(run_started_at - timedelta(seconds=10))

        repo.query(
            f"""
            INSERT INTO raw_packets (timestamp, packet_id, packet_name, session_uid, frame_id, data)
            VALUES ({stale_ts}, 2, 'lap_data', 9001, 1, '{{}}')
            """
        )
        repo.query(
            f"""
            INSERT INTO car_damage (timestamp, session_uid, car_index, tyres_wear_fl, tyres_wear_fr, tyres_wear_rl, tyres_wear_rr)
            VALUES ({stale_ts}, 9001, 0, 10, 11, 12, 13)
            """
        )
        repo.query(
            f"""
            INSERT INTO car_status (timestamp, session_uid, car_index, fuel_in_tank, fuel_remaining_laps, actual_tyre_compound, tyres_age_laps, ers_store_energy, ers_deploy_mode, fuel_mix)
            VALUES ({stale_ts}, 9001, 0, 30.0, 12.0, 16, 3, 2000000, 1, 1)
            """
        )
        repo.query(
            f"""
            INSERT INTO lap_data (timestamp, session_uid, car_index, last_lap_time_in_ms, car_position, delta_to_car_in_front_in_ms, delta_to_race_leader_in_ms, current_lap_num, num_pit_stops)
            VALUES ({stale_ts}, 9001, 0, 90000, 9, 600, 5000, 2, 0)
            """
        )
        repo.query(
            f"""
            INSERT INTO session_data (timestamp, session_uid, weather, track_temperature, air_temperature, total_laps, track_id, safety_car_status, rain_percentage, pit_stop_window_ideal_lap, pit_stop_window_latest_lap)
            VALUES ({stale_ts}, 9001, 0, 30, 22, 58, 5, 0, 0, 20, 30)
            """
        )

        snapshot = collect_strategy_snapshot(repo)
        assert snapshot["ready"] is False
        assert snapshot["reason"] == "waiting_for_live_packets"
    finally:
        repo.close()


def test_collect_strategy_snapshot_uses_active_run_and_session_uid():
    repo = DuckDBTelemetryRepository(":memory:")
    try:
        active_uid = 4242

        repo.query(
            """
            INSERT INTO session_data (session_uid, weather, track_temperature, air_temperature, total_laps, track_id, safety_car_status, rain_percentage, pit_stop_window_ideal_lap, pit_stop_window_latest_lap)
            VALUES (4242, 0, 32, 24, 58, 5, 0, 0, 18, 30)
            """
        )
        repo.query(
            """
            INSERT INTO raw_packets (packet_id, packet_name, session_uid, frame_id, data)
            VALUES (2, 'lap_data', 4242, 10, '{}')
            """
        )
        repo.query(
            """
            INSERT INTO car_damage (session_uid, car_index, tyres_wear_fl, tyres_wear_fr, tyres_wear_rl, tyres_wear_rr)
            VALUES (4242, 0, 15, 16, 17, 18)
            """
        )
        repo.query(
            """
            INSERT INTO car_status (session_uid, car_index, fuel_in_tank, fuel_remaining_laps, actual_tyre_compound, tyres_age_laps, ers_store_energy, ers_deploy_mode, fuel_mix)
            VALUES (4242, 0, 28.0, 10.5, 16, 8, 2500000, 1, 2)
            """
        )
        repo.query(
            """
            INSERT INTO lap_data (session_uid, car_index, last_lap_time_in_ms, car_position, delta_to_car_in_front_in_ms, delta_to_race_leader_in_ms, current_lap_num, num_pit_stops)
            VALUES (4242, 0, 89900, 7, 420, 2500, 6, 1)
            """
        )
        snapshot = collect_strategy_snapshot(repo)
        assert snapshot["ready"] is True
        assert snapshot["scope"]["session_uid"] == active_uid
        assert snapshot["race"]["current_lap"] == 6
    finally:
        repo.close()


def test_collect_strategy_snapshot_resets_between_session_types():
    repo = DuckDBTelemetryRepository(":memory:")
    try:
        run_started_at = repo.query(
            "SELECT started_at FROM app_runs ORDER BY started_at DESC LIMIT 1"
        )[0][0]
        p1_ts = _timestamp_literal(run_started_at + timedelta(seconds=5))
        p2_ts = _timestamp_literal(run_started_at + timedelta(seconds=25))

        # Practice session 1 data.
        repo.query(
            f"""
            INSERT INTO session_data (
                timestamp, session_uid, session_type, weather, track_temperature, air_temperature,
                total_laps, track_id, safety_car_status, rain_percentage,
                pit_stop_window_ideal_lap, pit_stop_window_latest_lap
            )
            VALUES ({p1_ts}, 7777, 5, 0, 31, 22, 20, 5, 0, 0, 7, 12)
            """
        )
        repo.query(
            f"""
            INSERT INTO car_status (
                timestamp, session_uid, car_index, fuel_in_tank, fuel_remaining_laps,
                actual_tyre_compound, tyres_age_laps, ers_store_energy, ers_deploy_mode, fuel_mix
            )
            VALUES ({p1_ts}, 7777, 0, 20.0, 9.0, 16, 5, 2200000, 1, 2)
            """
        )
        repo.query(
            f"""
            INSERT INTO car_damage (
                timestamp, session_uid, car_index, tyres_wear_fl, tyres_wear_fr, tyres_wear_rl, tyres_wear_rr
            )
            VALUES ({p1_ts}, 7777, 0, 21, 22, 23, 24)
            """
        )
        repo.query(
            f"""
            INSERT INTO lap_data (
                timestamp, session_uid, car_index, last_lap_time_in_ms, car_position,
                delta_to_car_in_front_in_ms, delta_to_race_leader_in_ms, current_lap_num, num_pit_stops
            )
            VALUES ({p1_ts}, 7777, 0, 92500, 11, 1200, 10000, 8, 0)
            """
        )

        # Practice session 2 starts later (same session_uid, different session_type).
        repo.query(
            f"""
            INSERT INTO session_data (
                timestamp, session_uid, session_type, weather, track_temperature, air_temperature,
                total_laps, track_id, safety_car_status, rain_percentage,
                pit_stop_window_ideal_lap, pit_stop_window_latest_lap
            )
            VALUES ({p2_ts}, 7777, 6, 0, 33, 24, 24, 5, 0, 0, 9, 16)
            """
        )
        repo.query(
            f"""
            INSERT INTO car_status (
                timestamp, session_uid, car_index, fuel_in_tank, fuel_remaining_laps,
                actual_tyre_compound, tyres_age_laps, ers_store_energy, ers_deploy_mode, fuel_mix
            )
            VALUES ({p2_ts}, 7777, 0, 25.0, 11.0, 17, 2, 2600000, 1, 2)
            """
        )
        repo.query(
            f"""
            INSERT INTO car_damage (
                timestamp, session_uid, car_index, tyres_wear_fl, tyres_wear_fr, tyres_wear_rl, tyres_wear_rr
            )
            VALUES ({p2_ts}, 7777, 0, 11, 12, 13, 14)
            """
        )
        repo.query(
            f"""
            INSERT INTO lap_data (
                timestamp, session_uid, car_index, last_lap_time_in_ms, car_position,
                delta_to_car_in_front_in_ms, delta_to_race_leader_in_ms, current_lap_num, num_pit_stops
            )
            VALUES ({p2_ts}, 7777, 0, 90500, 6, 450, 3200, 3, 0)
            """
        )

        snapshot = collect_strategy_snapshot(repo)
        assert snapshot["ready"] is True
        assert snapshot["scope"]["session_type"] == 6
        assert snapshot["race"]["current_lap"] == 3
        assert snapshot["race"]["position"] == 6
    finally:
        repo.close()
