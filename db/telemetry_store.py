import duckdb
import logging
import threading
from uuid import uuid4
from models.telemetry import TelemetryTick
from models.telemetry_packets import (
    PacketMotionData,
    PacketSessionData,
    PacketLapData,
    PacketEventData,
    PacketCarTelemetryData,
    PacketCarStatusData,
    PacketCarDamageData,
    PacketSessionHistoryData,
)
from services.event_bus_service import bus
from utils.telemetry_enums import PACKET_NAMES

logger = logging.getLogger(__name__)


class TelemetryStore:
    """
    Subscribes to all telemetry packet events and stores them in DuckDB.
    Two-tier storage:
      1. raw_packets: JSON blob dump of every packet (full fidelity, zero parsing)
      2. Analytical tables: curated tables for UI, analyzer, and strategy queries
    """

    def __init__(self, db_path: str = "telemetry.duckdb"):
        self.db_path = db_path
        self.conn = duckdb.connect(self.db_path)
        self._lock = threading.RLock()
        self._init_db()
        self.run_id = self._start_app_run()

        # Buffers for batched inserts
        self._telemetry_buffer = []
        self._raw_buffer = []
        self._session_buffer = []
        self._lap_data_buffer = []
        self._car_status_buffer = []
        self._car_damage_buffer = []
        self._telemetry_ext_buffer = []
        self._motion_buffer = []
        self._batch_size = 20  # Flush every ~1s at 20Hz

        # Subscribe to legacy telemetry_tick (backward compat)
        bus.subscribe("telemetry_tick", self._handle_tick)

        # Subscribe to all new packet topics
        bus.subscribe("packet_motion", self._handle_motion)
        bus.subscribe("packet_session", self._handle_session)
        bus.subscribe("packet_lap_data", self._handle_lap_data)
        bus.subscribe("packet_event", self._handle_event)
        bus.subscribe("packet_car_telemetry", self._handle_car_telemetry)
        bus.subscribe("packet_car_status", self._handle_car_status)
        bus.subscribe("packet_car_damage", self._handle_car_damage)
        bus.subscribe("packet_session_history", self._handle_session_history)
        # Raw dump for all packet types
        for topic in [
            "packet_motion",
            "packet_session",
            "packet_lap_data",
            "packet_event",
            "packet_participants",
            "packet_car_setup",
            "packet_car_telemetry",
            "packet_car_status",
            "packet_final_classification",
            "packet_lobby_info",
            "packet_car_damage",
            "packet_session_history",
            "packet_tyre_sets",
            "packet_motion_ex",
            "packet_time_trial",
            "packet_lap_positions",
        ]:
            bus.subscribe(topic, self._handle_raw_packet)

    def _init_db(self):
        from db.telemetry_schema import init_db

        init_db(self.conn, self.db_path)

    def _start_app_run(self) -> str:
        run_id = str(uuid4())
        self.conn.execute("INSERT INTO app_runs (run_id) VALUES (?)", [run_id])
        return run_id

    # --- Legacy telemetry_tick handler (backward compat) ---

    async def _handle_tick(self, tick: TelemetryTick):
        with self._lock:
            self._telemetry_buffer.append(
                (
                    tick.speed,
                    tick.gear,
                    tick.throttle,
                    tick.brake,
                    tick.steering,
                    tick.engine_rpm,
                    tick.tire_wear_fl,
                    tick.tire_wear_fr,
                    tick.tire_wear_rl,
                    tick.tire_wear_rr,
                    tick.lap,
                    tick.track_position,
                    tick.sector,
                )
            )
            if len(self._telemetry_buffer) >= self._batch_size:
                self._flush_telemetry()

    def _flush_telemetry(self):
        with self._lock:
            if not self._telemetry_buffer:
                return
            try:
                self.conn.executemany(
                    """
                    INSERT INTO telemetry (
                        speed, gear, throttle, brake, steering, engine_rpm,
                        tire_wear_fl, tire_wear_fr, tire_wear_rl, tire_wear_rr,
                        lap, track_position, sector
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    self._telemetry_buffer,
                )
                self._telemetry_buffer.clear()
            except Exception as e:
                logger.error(f"DuckDB telemetry insert error: {e}")

    # --- Raw packet dump handler ---

    async def _handle_raw_packet(self, packet):
        """Dump packets as JSON blobs into raw_packets table.

        High-frequency packets (20Hz: telemetry, lap_data, car_status, motion, motion_ex)
        are sampled at 1/20 rate (~1Hz) to keep storage manageable.
        Low-frequency packets (session, events, participants, etc.) are stored every time.
        """
        try:
            with self._lock:
                header = packet.header
                packet_id = header.packet_id
                packet_name = PACKET_NAMES.get(packet_id, f"unknown_{packet_id}")

                # Sample high-frequency packets (store every 20th = ~1Hz from 20Hz)
                high_freq_packets = {0, 2, 6, 7, 13}
                if packet_id in high_freq_packets:
                    if not hasattr(self, "_raw_sample_counters"):
                        self._raw_sample_counters = {}
                    count = self._raw_sample_counters.get(packet_id, 0) + 1
                    self._raw_sample_counters[packet_id] = count
                    if count % 20 != 0:
                        return

                data_json = packet.model_dump_json()
                self._raw_buffer.append(
                    (
                        packet_id,
                        packet_name,
                        header.session_uid,
                        header.frame_identifier,
                        data_json,
                    )
                )

                if len(self._raw_buffer) >= self._batch_size:
                    self._flush_raw()
        except Exception as e:
            logger.error(f"Raw packet buffer error: {e}")

    def _flush_raw(self):
        with self._lock:
            if not self._raw_buffer:
                return
            try:
                self.conn.executemany(
                    """
                    INSERT INTO raw_packets (packet_id, packet_name, session_uid, frame_id, data)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    self._raw_buffer,
                )
                self._raw_buffer.clear()
            except Exception as e:
                logger.error(f"DuckDB raw_packets insert error: {e}")

    # --- Analytical table handlers ---

    async def _handle_session(self, packet: PacketSessionData):
        """Store session data (low frequency)."""
        rain_pct = 0
        if packet.weather_forecast_samples:
            rain_pct = packet.weather_forecast_samples[0].rain_percentage
        try:
            with self._lock:
                self.conn.execute(
                    """
                    INSERT INTO session_data (
                        session_uid,
                        weather, track_temperature, air_temperature, total_laps,
                        track_length, session_type, track_id, session_time_left,
                        safety_car_status, rain_percentage,
                        pit_stop_window_ideal_lap, pit_stop_window_latest_lap
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    [
                        packet.header.session_uid,
                        packet.weather,
                        packet.track_temperature,
                        packet.air_temperature,
                        packet.total_laps,
                        packet.track_length,
                        packet.session_type,
                        packet.track_id,
                        packet.session_time_left,
                        packet.safety_car_status,
                        rain_pct,
                        packet.pit_stop_window_ideal_lap,
                        packet.pit_stop_window_latest_lap,
                    ],
                )
        except Exception as e:
            logger.error(f"DuckDB session_data insert error: {e}")

    async def _handle_lap_data(self, packet: PacketLapData):
        """Store player car lap data."""
        idx = packet.header.player_car_index
        if idx >= len(packet.car_lap_data):
            return
        lap = packet.car_lap_data[idx]
        with self._lock:
            self._lap_data_buffer.append(
                (
                    packet.header.session_uid,
                    idx,
                    lap.last_lap_time_in_ms,
                    lap.current_lap_time_in_ms,
                    lap.sector1_time_in_ms,
                    lap.sector2_time_in_ms,
                    lap.car_position,
                    lap.current_lap_num,
                    lap.pit_status,
                    lap.num_pit_stops,
                    lap.sector,
                    lap.penalties,
                    lap.driver_status,
                    lap.result_status,
                    lap.delta_to_car_in_front_in_ms,
                    lap.delta_to_race_leader_in_ms,
                    lap.speed_trap_fastest_speed,
                    lap.grid_position,
                )
            )
            if len(self._lap_data_buffer) >= self._batch_size:
                self._flush_lap_data()

    def _flush_lap_data(self):
        with self._lock:
            if not self._lap_data_buffer:
                return
            try:
                self.conn.executemany(
                    """
                    INSERT INTO lap_data (
                        session_uid, car_index, last_lap_time_in_ms, current_lap_time_in_ms,
                        sector1_time_in_ms, sector2_time_in_ms,
                        car_position, current_lap_num, pit_status, num_pit_stops,
                        sector, penalties, driver_status, result_status,
                        delta_to_car_in_front_in_ms, delta_to_race_leader_in_ms,
                        speed_trap_fastest_speed, grid_position
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    self._lap_data_buffer,
                )
                self._lap_data_buffer.clear()
            except Exception as e:
                logger.error(f"DuckDB lap_data insert error: {e}")

    async def _handle_car_status(self, packet: PacketCarStatusData):
        """Store player car status."""
        idx = packet.header.player_car_index
        if idx >= len(packet.car_status_data):
            return
        s = packet.car_status_data[idx]
        with self._lock:
            self._car_status_buffer.append(
                (
                    packet.header.session_uid,
                    idx,
                    s.fuel_mix,
                    s.fuel_in_tank,
                    s.fuel_remaining_laps,
                    s.ers_store_energy,
                    s.ers_deploy_mode,
                    s.ers_harvested_this_lap_mguk,
                    s.ers_harvested_this_lap_mguh,
                    s.ers_deployed_this_lap,
                    s.actual_tyre_compound,
                    s.visual_tyre_compound,
                    s.tyres_age_laps,
                    s.drs_allowed,
                    s.vehicle_fia_flags,
                    s.engine_power_ice,
                    s.engine_power_mguk,
                )
            )
            if len(self._car_status_buffer) >= self._batch_size:
                self._flush_car_status()

    def _flush_car_status(self):
        with self._lock:
            if not self._car_status_buffer:
                return
            try:
                self.conn.executemany(
                    """
                    INSERT INTO car_status (
                        session_uid, car_index, fuel_mix, fuel_in_tank, fuel_remaining_laps,
                        ers_store_energy, ers_deploy_mode,
                        ers_harvested_this_lap_mguk, ers_harvested_this_lap_mguh,
                        ers_deployed_this_lap, actual_tyre_compound,
                        visual_tyre_compound, tyres_age_laps, drs_allowed,
                        vehicle_fia_flags, engine_power_ice, engine_power_mguk
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    self._car_status_buffer,
                )
                self._car_status_buffer.clear()
            except Exception as e:
                logger.error(f"DuckDB car_status insert error: {e}")

    async def _handle_car_damage(self, packet: PacketCarDamageData):
        """Store player car damage."""
        idx = packet.header.player_car_index
        if idx >= len(packet.car_damage_data):
            return
        d = packet.car_damage_data[idx]
        with self._lock:
            self._car_damage_buffer.append(
                (
                    packet.header.session_uid,
                    idx,
                    d.tyres_wear[0],
                    d.tyres_wear[1],
                    d.tyres_wear[2],
                    d.tyres_wear[3],
                    d.tyres_damage[0],
                    d.tyres_damage[1],
                    d.tyres_damage[2],
                    d.tyres_damage[3],
                    d.front_left_wing_damage,
                    d.front_right_wing_damage,
                    d.rear_wing_damage,
                    d.floor_damage,
                    d.diffuser_damage,
                    d.sidepod_damage,
                    d.gear_box_damage,
                    d.engine_damage,
                    d.engine_mguh_wear,
                    d.engine_es_wear,
                    d.engine_ce_wear,
                    d.engine_ice_wear,
                    d.engine_mguk_wear,
                    d.engine_tc_wear,
                    d.drs_fault,
                    d.ers_fault,
                )
            )
            if len(self._car_damage_buffer) >= self._batch_size:
                self._flush_car_damage()

    def _flush_car_damage(self):
        with self._lock:
            if not self._car_damage_buffer:
                return
            try:
                self.conn.executemany(
                    """
                    INSERT INTO car_damage (
                        session_uid,
                        car_index,
                        tyres_wear_rl, tyres_wear_rr, tyres_wear_fl, tyres_wear_fr,
                        tyres_damage_rl, tyres_damage_rr, tyres_damage_fl, tyres_damage_fr,
                        front_left_wing_damage, front_right_wing_damage,
                        rear_wing_damage, floor_damage, diffuser_damage, sidepod_damage,
                        gear_box_damage, engine_damage,
                        engine_mguh_wear, engine_es_wear, engine_ce_wear,
                        engine_ice_wear, engine_mguk_wear, engine_tc_wear,
                        drs_fault, ers_fault
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    self._car_damage_buffer,
                )
                self._car_damage_buffer.clear()
            except Exception as e:
                logger.error(f"DuckDB car_damage insert error: {e}")

    async def _handle_car_telemetry(self, packet: PacketCarTelemetryData):
        """Store extended telemetry (temps, pressures) for player car."""
        idx = packet.header.player_car_index
        if idx >= len(packet.car_telemetry_data):
            return
        ct = packet.car_telemetry_data[idx]
        with self._lock:
            self._telemetry_ext_buffer.append(
                (
                    packet.header.session_uid,
                    idx,
                    ct.brakes_temperature[0],
                    ct.brakes_temperature[1],
                    ct.brakes_temperature[2],
                    ct.brakes_temperature[3],
                    ct.tyres_surface_temperature[0],
                    ct.tyres_surface_temperature[1],
                    ct.tyres_surface_temperature[2],
                    ct.tyres_surface_temperature[3],
                    ct.tyres_inner_temperature[0],
                    ct.tyres_inner_temperature[1],
                    ct.tyres_inner_temperature[2],
                    ct.tyres_inner_temperature[3],
                    ct.engine_temperature,
                    ct.tyres_pressure[0],
                    ct.tyres_pressure[1],
                    ct.tyres_pressure[2],
                    ct.tyres_pressure[3],
                    ct.drs,
                    ct.clutch,
                    packet.suggested_gear,
                )
            )
            if len(self._telemetry_ext_buffer) >= self._batch_size:
                self._flush_telemetry_ext()

    def _flush_telemetry_ext(self):
        with self._lock:
            if not self._telemetry_ext_buffer:
                return
            try:
                self.conn.executemany(
                    """
                    INSERT INTO car_telemetry_ext (
                        session_uid, car_index,
                        brakes_temp_rl, brakes_temp_rr, brakes_temp_fl, brakes_temp_fr,
                        tyres_surface_temp_rl, tyres_surface_temp_rr,
                        tyres_surface_temp_fl, tyres_surface_temp_fr,
                        tyres_inner_temp_rl, tyres_inner_temp_rr,
                        tyres_inner_temp_fl, tyres_inner_temp_fr,
                        engine_temperature,
                        tyres_pressure_rl, tyres_pressure_rr,
                        tyres_pressure_fl, tyres_pressure_fr,
                        drs, clutch, suggested_gear
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    self._telemetry_ext_buffer,
                )
                self._telemetry_ext_buffer.clear()
            except Exception as e:
                logger.error(f"DuckDB car_telemetry_ext insert error: {e}")

    async def _handle_event(self, packet: PacketEventData):
        """Store race events immediately."""
        detail_parts = []
        d = packet.event_details
        if d.vehicle_idx is not None:
            detail_parts.append(f"car={d.vehicle_idx}")
        if d.speed is not None:
            detail_parts.append(f"speed={d.speed:.1f}")
        if d.lap_time is not None:
            detail_parts.append(f"time={d.lap_time:.3f}")
        if d.overtaking_vehicle_idx is not None:
            detail_parts.append(f"overtaker={d.overtaking_vehicle_idx}")
        detail_text = ", ".join(detail_parts) if detail_parts else ""

        try:
            with self._lock:
                self.conn.execute(
                    """
                    INSERT INTO race_events (session_uid, event_code, vehicle_idx, detail_text)
                    VALUES (?, ?, ?, ?)
                """,
                    [packet.header.session_uid, packet.event_string_code, d.vehicle_idx, detail_text],
                )
        except Exception as e:
            logger.error(f"DuckDB race_events insert error: {e}")

    async def _handle_session_history(self, packet: PacketSessionHistoryData):
        """Store session history (per lap)."""
        try:
            with self._lock:
                for lap_num, lh in enumerate(packet.lap_history_data, start=1):
                    self.conn.execute(
                        """
                        INSERT INTO session_history (
                            session_uid,
                            car_index, lap_num, lap_time_in_ms,
                            sector1_time_in_ms, sector2_time_in_ms, sector3_time_in_ms,
                            lap_valid
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        [
                            packet.header.session_uid,
                            packet.car_idx,
                            lap_num,
                            lh.lap_time_in_ms,
                            lh.sector1_time_in_ms,
                            lh.sector2_time_in_ms,
                            lh.sector3_time_in_ms,
                            lh.lap_valid_bit_flags & 0x01,
                        ],
                    )
        except Exception as e:
            logger.error(f"DuckDB session_history insert error: {e}")

    async def _handle_motion(self, packet: PacketMotionData):
        """Store motion data (sampled - every 5th call)."""
        with self._lock:
            if not hasattr(self, "_motion_counter"):
                self._motion_counter = 0
            self._motion_counter += 1
            if self._motion_counter % 5 != 0:
                return

        idx = packet.header.player_car_index
        if idx >= len(packet.car_motion_data):
            return
        m = packet.car_motion_data[idx]
        with self._lock:
            self._motion_buffer.append(
                (
                    packet.header.session_uid,
                    idx,
                    m.world_position_x,
                    m.world_position_y,
                    m.world_position_z,
                    m.g_force_lateral,
                    m.g_force_longitudinal,
                    m.g_force_vertical,
                    m.yaw,
                    m.pitch,
                    m.roll,
                )
            )
            if len(self._motion_buffer) >= self._batch_size:
                self._flush_motion()

    def _flush_motion(self):
        with self._lock:
            if not self._motion_buffer:
                return
            try:
                self.conn.executemany(
                    """
                    INSERT INTO motion_data (
                        session_uid, car_index, world_position_x, world_position_y, world_position_z,
                        g_force_lateral, g_force_longitudinal, g_force_vertical,
                        yaw, pitch, roll
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    self._motion_buffer,
                )
                self._motion_buffer.clear()
            except Exception as e:
                logger.error(f"DuckDB motion_data insert error: {e}")

    # --- Query interface ---

    def query(self, sql: str):
        """Allows other components to query the database."""
        with self._lock:
            self._flush_all()
            return self.conn.execute(sql).fetchall()

    def _flush_all(self):
        """Flush all buffers."""
        self._flush_telemetry()
        self._flush_raw()
        self._flush_lap_data()
        self._flush_car_status()
        self._flush_car_damage()
        self._flush_telemetry_ext()
        self._flush_motion()

    def close(self):
        with self._lock:
            self._flush_all()
            self.conn.close()



