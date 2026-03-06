import time
import logging
import os
from models.telemetry import TelemetryTick, DrivingInsight
from models.telemetry_packets import (
    PacketCarStatusData,
    PacketCarDamageData,
    PacketSessionData,
    PacketEventData,
    PacketLapData,
    PacketCarTelemetryData,
)
from services.event_bus_service import bus
from utils.telemetry_enums import (
    EventCode,
    SAFETY_CAR_NAMES,
)

logger = logging.getLogger(__name__)


def _parse_float(raw: str | None, default: float) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class PerformanceAnalyzer:
    """
    Analyzes incoming telemetry data to detect performance issues and opportunities.
    Subscribes to both legacy telemetry_tick and new expanded packet topics.
    All 20Hz rules have cooldowns to prevent flooding the voice/UI systems.
    """

    def __init__(self):
        # Legacy subscriber
        bus.subscribe("telemetry_tick", self._handle_telemetry_tick)

        # New expanded packet subscribers
        bus.subscribe("packet_car_status", self._handle_car_status)
        bus.subscribe("packet_car_damage", self._handle_car_damage)
        bus.subscribe("packet_session", self._handle_session)
        bus.subscribe("packet_event", self._handle_event)
        bus.subscribe("packet_lap_data", self._handle_lap_data)
        bus.subscribe("packet_car_telemetry", self._handle_car_telemetry)

        # State tracking
        self.last_lap = 0
        self.tire_warning_issued = False
        self._fuel_warning_issued = False
        self._fuel_critical_issued = False
        self._ers_low_warned = False
        self._rain_warned = False
        self._safety_car_notified = False
        self._damage_warned = set()
        self._brake_temp_warned = False
        self._tire_temp_warned = False
        self._pit_window_notified = False
        self._last_position = 0
        self._overtake_lap = 0
        self._latest_lap_packet: PacketLapData | None = None
        self._latest_status_packet: PacketCarStatusData | None = None
        self._last_drs_allowed = 0
        self._drs_enable_notified_lap = 0

        # Cooldown timers (prevents flooding from 20Hz handlers)
        self._braking_in_zone = False  # True while brake > 0.5, resets on release
        self._braking_warned_this_zone = False  # One warning per braking zone
        self._last_position_check_time = 0.0  # Rate-limit position checks to 1/sec
        self._last_car_status_time = 0.0  # Rate-limit car_status checks to 1/sec
        self._last_car_telemetry_time = 0.0  # Rate-limit temp checks to 2/sec
        self._last_lockup_warning_time = 0.0
        self._lockup_warning_count_lap = 0
        self._lockup_repeated_warned_lap = False
        self._lockup_warning_cooldown_sec = _parse_float(
            os.getenv("FEEDBACK_LOCKUP_COOLDOWN_SEC"), 24.0
        )
        self._last_attack_call_time = 0.0
        self._last_attack_signature: str | None = None
        self._last_drs_enable_call_time = 0.0
        self._attack_call_cooldown_sec = _parse_float(
            os.getenv("FEEDBACK_ATTACK_CALL_COOLDOWN_SEC"), 12.0
        )
        self._drs_call_cooldown_sec = _parse_float(
            os.getenv("FEEDBACK_DRS_CALL_COOLDOWN_SEC"), 10.0
        )

    @staticmethod
    def _gap_seconds(delta_ms: int | None) -> float | None:
        if delta_ms is None:
            return None
        try:
            value = int(delta_ms)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        return value / 1000.0

    async def _maybe_publish_attack_call(self) -> None:
        if self._latest_lap_packet is None or self._latest_status_packet is None:
            return

        lap_idx = self._latest_lap_packet.header.player_car_index
        status_idx = self._latest_status_packet.header.player_car_index
        if lap_idx != status_idx:
            return
        if lap_idx >= len(self._latest_lap_packet.car_lap_data):
            return
        if lap_idx >= len(self._latest_status_packet.car_status_data):
            return

        lap = self._latest_lap_packet.car_lap_data[lap_idx]
        status = self._latest_status_packet.car_status_data[lap_idx]
        if lap.car_position <= 1:
            return
        if lap.pit_status != 0:
            return

        gap_front_s = self._gap_seconds(lap.delta_to_car_in_front_in_ms)
        if gap_front_s is None:
            return

        now = time.monotonic()
        ers_pct = max(0.0, min(100.0, (status.ers_store_energy / 4000000.0) * 100.0))

        if int(status.drs_allowed) == 1 and gap_front_s <= 0.9:
            if now - self._last_attack_call_time < self._drs_call_cooldown_sec:
                return
            gap_bucket = int(gap_front_s * 10)
            signature = f"drs_attack|lap{lap.current_lap_num}|g{gap_bucket}"
            if signature == self._last_attack_signature:
                return
            message = (
                f"DRS is available. Gap {gap_front_s:.1f} seconds. Use overtake now."
                if ers_pct >= 20.0
                else (
                    f"DRS is available. Gap {gap_front_s:.1f} seconds. Attack, but manage ERS this straight."
                )
            )
            self._last_attack_call_time = now
            self._last_attack_signature = signature
            await bus.publish(
                "driving_insight",
                DrivingInsight(
                    message=message,
                    type="strategy",
                    priority=4,
                ),
            )
            return

        if int(status.drs_allowed) == 0 and gap_front_s <= 0.6:
            if now - self._last_attack_call_time < self._attack_call_cooldown_sec:
                return
            gap_bucket = int(gap_front_s * 10)
            signature = f"setup_drs|lap{lap.current_lap_num}|g{gap_bucket}"
            if signature == self._last_attack_signature:
                return
            self._last_attack_call_time = now
            self._last_attack_signature = signature
            await bus.publish(
                "driving_insight",
                DrivingInsight(
                    message=(
                        f"Gap to the car ahead is {gap_front_s:.1f} seconds. "
                        "Stay in slipstream and prep DRS for the next zone."
                    ),
                    type="strategy",
                    priority=3,
                ),
            )

    async def _handle_telemetry_tick(self, data: TelemetryTick):
        """Legacy handler - lap detection, braking, tire wear."""
        # Lap detection
        if data.lap > self.last_lap:
            self.last_lap = data.lap
            self.tire_warning_issued = False
            self._brake_temp_warned = False
            self._tire_temp_warned = False
            self._ers_low_warned = False
            self._lockup_warning_count_lap = 0
            self._lockup_repeated_warned_lap = False
            logger.info(f"Feedback Engine: Detected new lap {self.last_lap}.")

            insight = DrivingInsight(
                message=f"Lap {self.last_lap} started. Keep the momentum going.",
                type="encouragement",
                priority=2,
            )
            await bus.publish("driving_insight", insight)

        # Hard braking - debounce: one warning per braking zone
        if data.brake > 0.5:
            if not self._braking_in_zone:
                self._braking_in_zone = True
                self._braking_warned_this_zone = False

            if (
                data.brake > 0.8
                and data.speed > 250
                and not self._braking_warned_this_zone
            ):
                self._braking_warned_this_zone = True
                now = time.monotonic()
                if (now - self._last_lockup_warning_time) >= self._lockup_warning_cooldown_sec:
                    self._last_lockup_warning_time = now
                    self._lockup_warning_count_lap += 1

                    if self._lockup_warning_count_lap >= 3:
                        if self._lockup_repeated_warned_lap:
                            insight = None
                        else:
                            self._lockup_repeated_warned_lap = True
                            insight = DrivingInsight(
                                message="Repeated lockups this lap. Brake earlier and release pressure smoothly.",
                                type="warning",
                                priority=4,
                            )
                    else:
                        insight = DrivingInsight(
                            message="Careful on brake entry, avoid locking the fronts in this zone.",
                            type="info",
                            priority=3,
                        )
                    if insight is not None:
                        await bus.publish("driving_insight", insight)
        else:
            # Released brakes - reset for next zone
            self._braking_in_zone = False

        # Tire wear
        max_wear = max(
            data.tire_wear_fl, data.tire_wear_fr, data.tire_wear_rl, data.tire_wear_rr
        )
        if max_wear > 60.0 and not self.tire_warning_issued:
            self.tire_warning_issued = True
            insight = DrivingInsight(
                message="Tires are heavily worn. You might want to consider boxing in the next few laps.",
                type="strategy",
                priority=5,
            )
            await bus.publish("driving_insight", insight)

    async def _handle_car_status(self, packet: PacketCarStatusData):
        """Fuel management, ERS strategy. Rate-limited to 1Hz."""
        now = time.monotonic()
        if now - self._last_car_status_time < 1.0:
            return
        self._last_car_status_time = now
        self._latest_status_packet = packet

        idx = packet.header.player_car_index
        if idx >= len(packet.car_status_data):
            return
        s = packet.car_status_data[idx]

        # Fuel warning: < 3.0 laps remaining
        if s.fuel_remaining_laps < 3.0 and not self._fuel_warning_issued:
            self._fuel_warning_issued = True
            await bus.publish(
                "driving_insight",
                DrivingInsight(
                    message=f"Fuel is critical! Only {s.fuel_remaining_laps:.1f} laps of fuel remaining. Consider fuel saving.",
                    type="warning",
                    priority=5,
                ),
            )
        elif s.fuel_remaining_laps < 5.0 and not self._fuel_critical_issued:
            self._fuel_critical_issued = True
            await bus.publish(
                "driving_insight",
                DrivingInsight(
                    message=f"Fuel is getting low - {s.fuel_remaining_laps:.1f} laps remaining. Keep an eye on it.",
                    type="info",
                    priority=3,
                ),
            )

        # ERS low warning
        ers_pct = s.ers_store_energy / 4000000.0 * 100
        if ers_pct < 10 and not self._ers_low_warned:
            self._ers_low_warned = True
            await bus.publish(
                "driving_insight",
                DrivingInsight(
                    message=f"ERS battery at {ers_pct:.0f}%. Harvest more before the next overtake opportunity.",
                    type="info",
                    priority=3,
                ),
            )
        elif ers_pct > 30:
            self._ers_low_warned = False

        drs_allowed_now = int(s.drs_allowed)
        if drs_allowed_now == 1 and self._last_drs_allowed == 0:
            lap_num = self.last_lap
            if self._latest_lap_packet is not None and idx < len(self._latest_lap_packet.car_lap_data):
                lap_num = self._latest_lap_packet.car_lap_data[idx].current_lap_num
            if (
                lap_num != self._drs_enable_notified_lap
                and (now - self._last_drs_enable_call_time) >= self._drs_call_cooldown_sec
            ):
                self._drs_enable_notified_lap = lap_num
                self._last_drs_enable_call_time = now
                await bus.publish(
                    "driving_insight",
                    DrivingInsight(
                        message="DRS enabled. Prioritize clean exit and deploy on the straight.",
                        type="strategy",
                        priority=4,
                    ),
                )
        self._last_drs_allowed = drs_allowed_now
        await self._maybe_publish_attack_call()

    async def _handle_car_damage(self, packet: PacketCarDamageData):
        """Damage critical alerts."""
        idx = packet.header.player_car_index
        if idx >= len(packet.car_damage_data):
            return
        d = packet.car_damage_data[idx]

        damage_components = {
            "Front left wing": d.front_left_wing_damage,
            "Front right wing": d.front_right_wing_damage,
            "Rear wing": d.rear_wing_damage,
            "Floor": d.floor_damage,
            "Diffuser": d.diffuser_damage,
            "Sidepod": d.sidepod_damage,
            "Gearbox": d.gear_box_damage,
            "Engine": d.engine_damage,
        }

        for name, pct in damage_components.items():
            if pct > 50 and name not in self._damage_warned:
                self._damage_warned.add(name)
                await bus.publish(
                    "driving_insight",
                    DrivingInsight(
                        message=f"{name} damage is at {pct}%! This could affect performance significantly.",
                        type="warning",
                        priority=5,
                    ),
                )

    async def _handle_session(self, packet: PacketSessionData):
        """Weather alerts, safety car, pit window. Already 2Hz so no extra throttle needed."""
        # Rain incoming
        rain_pct = 0
        for forecast in packet.weather_forecast_samples:
            if forecast.time_offset <= 10 and forecast.rain_percentage > 50:
                rain_pct = forecast.rain_percentage
                break

        if rain_pct > 50 and not self._rain_warned:
            self._rain_warned = True
            await bus.publish(
                "driving_insight",
                DrivingInsight(
                    message=f"Rain forecast at {rain_pct}% probability in the next 10 minutes. Standby for potential tire change.",
                    type="strategy",
                    priority=4,
                ),
            )
        elif rain_pct <= 20:
            self._rain_warned = False

        # Safety car
        if packet.safety_car_status > 0 and not self._safety_car_notified:
            self._safety_car_notified = True
            sc_name = SAFETY_CAR_NAMES.get(packet.safety_car_status, "Safety Car")
            await bus.publish(
                "driving_insight",
                DrivingInsight(
                    message=f"{sc_name} deployed! Manage your tires and prepare for restart.",
                    type="warning",
                    priority=5,
                ),
            )
        elif packet.safety_car_status == 0:
            self._safety_car_notified = False

    async def _handle_event(self, packet: PacketEventData):
        """React to race events. These are already infrequent."""
        code = packet.event_string_code
        d = packet.event_details

        if code == EventCode.FASTEST_LAP and d.vehicle_idx is not None:
            await bus.publish(
                "driving_insight",
                DrivingInsight(
                    message=f"Fastest lap set by car {d.vehicle_idx}!",
                    type="info",
                    priority=2,
                ),
            )

        elif code == EventCode.SAFETY_CAR:
            await bus.publish(
                "driving_insight",
                DrivingInsight(
                    message="Safety car has been deployed.", type="warning", priority=5
                ),
            )

        elif code == EventCode.LIGHTS_OUT:
            await bus.publish(
                "driving_insight",
                DrivingInsight(
                    message="Lights out and away we go! Good start, keep it clean.",
                    type="encouragement",
                    priority=4,
                ),
            )

    async def _handle_lap_data(self, packet: PacketLapData):
        """Position changes. Rate-limited to 1Hz to avoid noisy data."""
        now = time.monotonic()
        if now - self._last_position_check_time < 1.0:
            return
        self._last_position_check_time = now
        self._latest_lap_packet = packet

        idx = packet.header.player_car_index
        if idx >= len(packet.car_lap_data):
            return
        lap = packet.car_lap_data[idx]

        # Position change detection
        if self._last_position > 0 and lap.car_position < self._last_position:
            if self._overtake_lap != lap.current_lap_num:
                self._overtake_lap = lap.current_lap_num
                await bus.publish(
                    "driving_insight",
                    DrivingInsight(
                        message=f"Great move! You're up to P{lap.car_position}.",
                        type="encouragement",
                        priority=3,
                    ),
                )
        elif self._last_position > 0 and lap.car_position > self._last_position:
            if self._overtake_lap != lap.current_lap_num:
                self._overtake_lap = lap.current_lap_num
                await bus.publish(
                    "driving_insight",
                    DrivingInsight(
                        message=f"Lost a position, now P{lap.car_position}. Push to get it back.",
                        type="info",
                        priority=3,
                    ),
                )
        self._last_position = lap.car_position
        await self._maybe_publish_attack_call()

    async def _handle_car_telemetry(self, packet: PacketCarTelemetryData):
        """Tire and brake temperature warnings. Rate-limited to 0.5Hz."""
        now = time.monotonic()
        if now - self._last_car_telemetry_time < 2.0:
            return
        self._last_car_telemetry_time = now

        idx = packet.header.player_car_index
        if idx >= len(packet.car_telemetry_data):
            return
        ct = packet.car_telemetry_data[idx]

        # Brake temperature > 900C
        max_brake = max(ct.brakes_temperature)
        if max_brake > 900 and not self._brake_temp_warned:
            self._brake_temp_warned = True
            await bus.publish(
                "driving_insight",
                DrivingInsight(
                    message=f"Brake temperatures are very high at {max_brake}C! Ease the braking or you risk brake failure.",
                    type="warning",
                    priority=4,
                ),
            )

        # Tire surface temp out of window
        max_surf = max(ct.tyres_surface_temperature)
        min_surf = min(ct.tyres_surface_temperature)
        if (max_surf > 110 or min_surf < 80) and not self._tire_temp_warned:
            self._tire_temp_warned = True
            if max_surf > 110:
                await bus.publish(
                    "driving_insight",
                    DrivingInsight(
                        message=f"Tire surface temperature is {max_surf}C - overheating. Manage your inputs.",
                        type="warning",
                        priority=3,
                    ),
                )
            else:
                await bus.publish(
                    "driving_insight",
                    DrivingInsight(
                        message=f"Tire surface temperature is {min_surf}C - tires are cold. Push to build heat.",
                        type="info",
                        priority=2,
                    ),
                )


