import logging

logger = logging.getLogger(__name__)


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    columns = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    return any(str(col[1]).lower() == column_name.lower() for col in columns)


def _ensure_column(
    conn,
    table_name: str,
    column_name: str,
    column_type: str,
    default_sql: str | None = None,
) -> None:
    if _column_exists(conn, table_name, column_name):
        return
    statement = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
    if default_sql:
        statement = f"{statement} DEFAULT {default_sql}"
    conn.execute(statement)


def init_db(conn, db_path: str):
    """Creates all tables if they don't exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_runs (
            run_id VARCHAR PRIMARY KEY,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # Legacy telemetry table (backward compat)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS telemetry (
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            speed DOUBLE,
            gear INTEGER,
            throttle DOUBLE,
            brake DOUBLE,
            steering DOUBLE,
            engine_rpm INTEGER,
            tire_wear_fl DOUBLE,
            tire_wear_fr DOUBLE,
            tire_wear_rl DOUBLE,
            tire_wear_rr DOUBLE,
            lap INTEGER,
            track_position DOUBLE,
            sector INTEGER
        )
    """)
    
    # Raw packets table (zero-parsing dump)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_packets (
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            packet_id INTEGER,
            packet_name VARCHAR,
            session_uid BIGINT,
            frame_id INTEGER,
            data JSON
        )
    """)
    
    # Session data (low frequency)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_data (
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_uid BIGINT,
            weather INTEGER,
            track_temperature INTEGER,
            air_temperature INTEGER,
            total_laps INTEGER,
            track_length INTEGER,
            session_type INTEGER,
            track_id INTEGER,
            session_time_left INTEGER,
            safety_car_status INTEGER,
            rain_percentage INTEGER,
            pit_stop_window_ideal_lap INTEGER,
            pit_stop_window_latest_lap INTEGER
        )
    """)
    
    # Per-car lap timing data
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lap_data (
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_uid BIGINT,
            car_index INTEGER,
            last_lap_time_in_ms INTEGER,
            current_lap_time_in_ms INTEGER,
            sector1_time_in_ms INTEGER,
            sector2_time_in_ms INTEGER,
            car_position INTEGER,
            current_lap_num INTEGER,
            pit_status INTEGER,
            num_pit_stops INTEGER,
            sector INTEGER,
            penalties INTEGER,
            driver_status INTEGER,
            result_status INTEGER,
            delta_to_car_in_front_in_ms INTEGER,
            delta_to_race_leader_in_ms INTEGER,
            speed_trap_fastest_speed DOUBLE,
            grid_position INTEGER
        )
    """)
    
    # Per-car status (fuel, ERS, tires)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS car_status (
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_uid BIGINT,
            car_index INTEGER,
            fuel_mix INTEGER,
            fuel_in_tank DOUBLE,
            fuel_remaining_laps DOUBLE,
            ers_store_energy DOUBLE,
            ers_deploy_mode INTEGER,
            ers_harvested_this_lap_mguk DOUBLE,
            ers_harvested_this_lap_mguh DOUBLE,
            ers_deployed_this_lap DOUBLE,
            actual_tyre_compound INTEGER,
            visual_tyre_compound INTEGER,
            tyres_age_laps INTEGER,
            drs_allowed INTEGER,
            vehicle_fia_flags INTEGER,
            engine_power_ice DOUBLE,
            engine_power_mguk DOUBLE
        )
    """)
    
    # Per-car damage
    conn.execute("""
        CREATE TABLE IF NOT EXISTS car_damage (
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_uid BIGINT,
            car_index INTEGER,
            tyres_wear_rl DOUBLE,
            tyres_wear_rr DOUBLE,
            tyres_wear_fl DOUBLE,
            tyres_wear_fr DOUBLE,
            tyres_damage_rl INTEGER,
            tyres_damage_rr INTEGER,
            tyres_damage_fl INTEGER,
            tyres_damage_fr INTEGER,
            front_left_wing_damage INTEGER,
            front_right_wing_damage INTEGER,
            rear_wing_damage INTEGER,
            floor_damage INTEGER,
            diffuser_damage INTEGER,
            sidepod_damage INTEGER,
            gear_box_damage INTEGER,
            engine_damage INTEGER,
            engine_mguh_wear INTEGER,
            engine_es_wear INTEGER,
            engine_ce_wear INTEGER,
            engine_ice_wear INTEGER,
            engine_mguk_wear INTEGER,
            engine_tc_wear INTEGER,
            drs_fault INTEGER,
            ers_fault INTEGER
        )
    """)
    
    # Extended telemetry (temps, pressures)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS car_telemetry_ext (
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_uid BIGINT,
            car_index INTEGER,
            brakes_temp_rl INTEGER,
            brakes_temp_rr INTEGER,
            brakes_temp_fl INTEGER,
            brakes_temp_fr INTEGER,
            tyres_surface_temp_rl INTEGER,
            tyres_surface_temp_rr INTEGER,
            tyres_surface_temp_fl INTEGER,
            tyres_surface_temp_fr INTEGER,
            tyres_inner_temp_rl INTEGER,
            tyres_inner_temp_rr INTEGER,
            tyres_inner_temp_fl INTEGER,
            tyres_inner_temp_fr INTEGER,
            engine_temperature INTEGER,
            tyres_pressure_rl DOUBLE,
            tyres_pressure_rr DOUBLE,
            tyres_pressure_fl DOUBLE,
            tyres_pressure_fr DOUBLE,
            drs INTEGER,
            clutch INTEGER,
            suggested_gear INTEGER
        )
    """)
    
    # Race events log
    conn.execute("""
        CREATE TABLE IF NOT EXISTS race_events (
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_uid BIGINT,
            event_code VARCHAR,
            vehicle_idx INTEGER,
            detail_text VARCHAR
        )
    """)
    
    # Session history (per lap)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_history (
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_uid BIGINT,
            car_index INTEGER,
            lap_num INTEGER,
            lap_time_in_ms INTEGER,
            sector1_time_in_ms INTEGER,
            sector2_time_in_ms INTEGER,
            sector3_time_in_ms INTEGER,
            lap_valid INTEGER
        )
    """)
    
    # Motion data (sampled)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS motion_data (
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_uid BIGINT,
            car_index INTEGER,
            world_position_x DOUBLE,
            world_position_y DOUBLE,
            world_position_z DOUBLE,
            g_force_lateral DOUBLE,
            g_force_longitudinal DOUBLE,
            g_force_vertical DOUBLE,
            yaw DOUBLE,
            pitch DOUBLE,
            roll DOUBLE
        )
    """)

    # Lightweight migrations for users on older schemas.
    _ensure_column(conn, "session_data", "session_uid", "BIGINT")
    _ensure_column(conn, "lap_data", "session_uid", "BIGINT")
    _ensure_column(conn, "car_status", "session_uid", "BIGINT")
    _ensure_column(conn, "car_damage", "session_uid", "BIGINT")
    _ensure_column(conn, "car_telemetry_ext", "session_uid", "BIGINT")
    _ensure_column(conn, "race_events", "session_uid", "BIGINT")
    _ensure_column(conn, "session_history", "timestamp", "TIMESTAMP", "CURRENT_TIMESTAMP")
    _ensure_column(conn, "session_history", "session_uid", "BIGINT")
    _ensure_column(conn, "motion_data", "session_uid", "BIGINT")
    
    logger.info(f"TelemetryStore initialized at {db_path} with all tables.")
    
    

