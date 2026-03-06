import logging
import os
from collections import deque
from typing import Any, Optional

from agents.race_engineer_agent import RaceEngineerAgent
from models.engineer_agent import EngineerReply
from models.strategy import StrategyInsight
from models.telemetry import TelemetryTick, DriverQuery, DrivingInsight
from models.telemetry_packets import (
    PacketMotionData,
    PacketCarStatusData,
    PacketCarDamageData,
    PacketSessionData,
    PacketLapData,
    PacketEventData,
    PacketParticipantsData,
    PacketCarSetupData,
    PacketCarTelemetryData,
    PacketFinalClassificationData,
    PacketLobbyInfoData,
    PacketSessionHistoryData,
    PacketTyreSetsData,
    PacketMotionExData,
    PacketTimeTrialData,
    PacketLapPositions,
)
from services.event_bus_service import bus
from services.llm_factory import ChatClient
from utils.telemetry_enums import TYRE_COMPOUND_SHORT, WEATHER_NAMES, SESSION_TYPE_NAMES, TRACK_NAMES
from utils.radio_character_guard import is_out_of_character_response
from utils.radio_context import build_radio_context
from utils.radio_personality import (
    apply_persona_fillers,
    choose_engineer_persona,
    detect_driver_tone,
    next_rapport_level,
    persona_instruction,
    tone_instruction,
)
from utils.radio_text import to_radio_brief

logger = logging.getLogger(__name__)


class RaceEngineerService:
    """
    Acts as the brain of the Race Engineer.
    Maintains the latest telemetry state from expanded packets and uses the configured LLM
    to answer driver queries dynamically with full race context.
    """

    def __init__(self):
        self.client = ChatClient(role="advisor", temperature=0.3)
        self._rapport_level = 1
        self._active_persona = "focused_teammate"
        self._conversation_history: deque[str] = deque(maxlen=12)
        self._driver_preference = "standard"
        self._agent = RaceEngineerAgent(
            telemetry_provider=self,
            thread_id=os.getenv("RACE_ENGINEER_THREAD_ID", "race-engineer-main"),
        )

        # State tracking (legacy)
        self.latest_telemetry: Optional[TelemetryTick] = None
        self.latest_strategy: Optional[StrategyInsight] = None

        # Expanded state tracking
        self._car_status: Optional[PacketCarStatusData] = None
        self._car_damage: Optional[PacketCarDamageData] = None
        self._session: Optional[PacketSessionData] = None
        self._lap_data: Optional[PacketLapData] = None
        self._car_telemetry: Optional[PacketCarTelemetryData] = None
        self._motion: Optional[PacketMotionData] = None
        self._event: Optional[PacketEventData] = None
        self._participants: Optional[PacketParticipantsData] = None
        self._car_setup: Optional[PacketCarSetupData] = None
        self._final_classification: Optional[PacketFinalClassificationData] = None
        self._lobby_info: Optional[PacketLobbyInfoData] = None
        self._session_history: dict[int, PacketSessionHistoryData] = {}
        self._tyre_sets: Optional[PacketTyreSetsData] = None
        self._motion_ex: Optional[PacketMotionExData] = None
        self._time_trial: Optional[PacketTimeTrialData] = None
        self._lap_positions: Optional[PacketLapPositions] = None
        self._event_log: deque[PacketEventData] = deque(maxlen=50)
        self._player_idx: int = 0

        # Subscribe to data
        bus.subscribe("telemetry_tick", self._update_telemetry)
        bus.subscribe("strategy_insight", self._update_strategy)
        bus.subscribe("driver_query", self._handle_query)
        bus.subscribe("packet_car_status", self._update_car_status)
        bus.subscribe("packet_car_damage", self._update_car_damage)
        bus.subscribe("packet_session", self._update_session)
        bus.subscribe("packet_lap_data", self._update_lap_data)
        bus.subscribe("packet_car_telemetry", self._update_car_telemetry)
        bus.subscribe("packet_motion", self._update_motion)
        bus.subscribe("packet_event", self._update_event)
        bus.subscribe("packet_participants", self._update_participants)
        bus.subscribe("packet_car_setup", self._update_car_setup)
        bus.subscribe("packet_final_classification", self._update_final_classification)
        bus.subscribe("packet_lobby_info", self._update_lobby_info)
        bus.subscribe("packet_session_history", self._update_session_history)
        bus.subscribe("packet_tyre_sets", self._update_tyre_sets)
        bus.subscribe("packet_motion_ex", self._update_motion_ex)
        bus.subscribe("packet_time_trial", self._update_time_trial)
        bus.subscribe("packet_lap_positions", self._update_lap_positions)

    async def _update_telemetry(self, tick: TelemetryTick):
        self.latest_telemetry = tick

    async def _update_strategy(self, insight: StrategyInsight):
        self.latest_strategy = insight
        if insight.criticality >= 4:
            logger.info(
                f"LLM Advisor received CRITICAL strategy: {insight.recommendation}"
            )
            await self._send_insight(
                f"Strategy Team update: {insight.recommendation}",
                "strategy",
                insight.criticality,
            )

    async def _update_car_status(self, data: PacketCarStatusData):
        self._car_status = data
        self._player_idx = data.header.player_car_index

    async def _update_car_damage(self, data: PacketCarDamageData):
        self._car_damage = data

    async def _update_session(self, data: PacketSessionData):
        self._session = data

    async def _update_lap_data(self, data: PacketLapData):
        self._lap_data = data

    async def _update_car_telemetry(self, data: PacketCarTelemetryData):
        self._car_telemetry = data

    async def _update_motion(self, data: PacketMotionData):
        self._motion = data

    async def _update_event(self, data: PacketEventData):
        self._event = data
        self._event_log.append(data)

    async def _update_participants(self, data: PacketParticipantsData):
        self._participants = data

    async def _update_car_setup(self, data: PacketCarSetupData):
        self._car_setup = data

    async def _update_final_classification(self, data: PacketFinalClassificationData):
        self._final_classification = data

    async def _update_lobby_info(self, data: PacketLobbyInfoData):
        self._lobby_info = data

    async def _update_session_history(self, data: PacketSessionHistoryData):
        self._session_history[data.car_idx] = data

    async def _update_tyre_sets(self, data: PacketTyreSetsData):
        self._tyre_sets = data

    async def _update_motion_ex(self, data: PacketMotionExData):
        self._motion_ex = data

    async def _update_time_trial(self, data: PacketTimeTrialData):
        self._time_trial = data

    async def _update_lap_positions(self, data: PacketLapPositions):
        self._lap_positions = data

    def _build_context(self) -> str:
        """Build a rich context string from all available data."""
        return build_radio_context(
            telemetry=self.latest_telemetry,
            strategy=self.latest_strategy,
            car_status=self._car_status,
            car_damage=self._car_damage,
            session=self._session,
            lap_data=self._lap_data,
            player_idx=self._player_idx,
        )

    @staticmethod
    def _safe_indexed(items: list[Any], index: int) -> Any | None:
        if index < 0 or index >= len(items):
            return None
        return items[index]

    def get_gap_snapshot(self) -> dict[str, Any]:
        lap_packet = self._lap_data
        if lap_packet is None:
            return {"available": False}
        lap = self._safe_indexed(lap_packet.car_lap_data, self._player_idx)
        if lap is None:
            return {"available": False}
        return {
            "available": True,
            "lap": lap.current_lap_num,
            "position": lap.car_position,
            "gap_front_ms": lap.delta_to_car_in_front_in_ms,
            "gap_leader_ms": lap.delta_to_race_leader_in_ms,
            "last_lap_ms": lap.last_lap_time_in_ms,
            "pit_stops": lap.num_pit_stops,
        }

    def get_car_state_snapshot(self) -> dict[str, Any]:
        status_packet = self._car_status
        if status_packet is None:
            return {"available": False}
        status = self._safe_indexed(status_packet.car_status_data, self._player_idx)
        if status is None:
            return {"available": False}
        ers_pct = max(0.0, min(100.0, (status.ers_store_energy / 4000000.0) * 100.0))
        return {
            "available": True,
            "fuel_remaining_laps": status.fuel_remaining_laps,
            "fuel_in_tank": status.fuel_in_tank,
            "ers_pct": ers_pct,
            "ers_mode": status.ers_deploy_mode,
            "drs_available": bool(status.drs_allowed),
            "tyre_age_laps": status.tyres_age_laps,
            "compound": TYRE_COMPOUND_SHORT.get(status.visual_tyre_compound, "UNK"),
        }

    def get_health_snapshot(self) -> dict[str, Any]:
        max_brake: int | None = None
        max_tire: int | None = None
        max_damage: int | None = None
        max_damage_component: str | None = None

        if self._car_telemetry is not None:
            telemetry = self._safe_indexed(
                self._car_telemetry.car_telemetry_data,
                self._player_idx,
            )
            if telemetry is not None:
                max_brake = max(telemetry.brakes_temperature) if telemetry.brakes_temperature else None
                max_tire = (
                    max(telemetry.tyres_surface_temperature)
                    if telemetry.tyres_surface_temperature
                    else None
                )

        if self._car_damage is not None:
            damage = self._safe_indexed(self._car_damage.car_damage_data, self._player_idx)
            if damage is not None:
                components = {
                    "front_left_wing": damage.front_left_wing_damage,
                    "front_right_wing": damage.front_right_wing_damage,
                    "rear_wing": damage.rear_wing_damage,
                    "floor": damage.floor_damage,
                    "diffuser": damage.diffuser_damage,
                    "sidepod": damage.sidepod_damage,
                    "gearbox": damage.gear_box_damage,
                    "engine": damage.engine_damage,
                }
                sorted_components = sorted(
                    components.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
                if sorted_components:
                    max_damage_component, max_damage = sorted_components[0]

        available = any(v is not None for v in (max_brake, max_tire, max_damage))
        return {
            "available": available,
            "max_brake_temp_c": max_brake,
            "max_tire_surface_temp_c": max_tire,
            "max_damage_component": max_damage_component,
            "max_damage_pct": max_damage,
        }

    def _participant_name(self, index: int) -> str | None:
        if self._participants is None:
            return None
        participant = self._safe_indexed(self._participants.participants, index)
        if participant is None:
            return None
        name = (participant.name or "").strip()
        return name or None

    def get_full_telemetry_snapshot(self) -> dict[str, Any]:
        """Expose all available telemetry packet families for agent tools."""
        gap = self.get_gap_snapshot()
        car_state = self.get_car_state_snapshot()
        health = self.get_health_snapshot()

        session_payload: dict[str, Any] = {}
        if self._session is not None:
            session_payload = {
                "weather_code": self._session.weather,
                "weather": WEATHER_NAMES.get(self._session.weather, str(self._session.weather)),
                "track_temperature_c": self._session.track_temperature,
                "air_temperature_c": self._session.air_temperature,
                "rain_percentage": (
                    self._session.weather_forecast_samples[0].rain_percentage
                    if self._session.weather_forecast_samples
                    else 0
                ),
                "total_laps": self._session.total_laps,
                "session_type_code": self._session.session_type,
                "session_type": SESSION_TYPE_NAMES.get(
                    self._session.session_type,
                    str(self._session.session_type),
                ),
                "track_id": self._session.track_id,
                "track": TRACK_NAMES.get(self._session.track_id, str(self._session.track_id)),
                "safety_car_status": self._session.safety_car_status,
                "pit_window_ideal_lap": self._session.pit_stop_window_ideal_lap,
                "pit_window_latest_lap": self._session.pit_stop_window_latest_lap,
            }

        setup_payload: dict[str, Any] = {}
        if self._car_setup is not None:
            setup = self._safe_indexed(self._car_setup.car_setups, self._player_idx)
            if setup is not None:
                setup_payload = {
                    "front_wing": setup.front_wing,
                    "rear_wing": setup.rear_wing,
                    "on_throttle_diff": setup.on_throttle,
                    "off_throttle_diff": setup.off_throttle,
                    "brake_bias": setup.brake_bias,
                    "brake_pressure": setup.brake_pressure,
                    "front_suspension": setup.front_suspension,
                    "rear_suspension": setup.rear_suspension,
                    "fuel_load": setup.fuel_load,
                }

        motion_payload: dict[str, Any] = {}
        if self._motion is not None:
            motion = self._safe_indexed(self._motion.car_motion_data, self._player_idx)
            if motion is not None:
                motion_payload = {
                    "world_position": [
                        motion.world_position_x,
                        motion.world_position_y,
                        motion.world_position_z,
                    ],
                    "world_velocity": [
                        motion.world_velocity_x,
                        motion.world_velocity_y,
                        motion.world_velocity_z,
                    ],
                    "g_force_lateral": motion.g_force_lateral,
                    "g_force_longitudinal": motion.g_force_longitudinal,
                    "g_force_vertical": motion.g_force_vertical,
                    "yaw": motion.yaw,
                    "pitch": motion.pitch,
                    "roll": motion.roll,
                }

        motion_ex_payload: dict[str, Any] = {}
        if self._motion_ex is not None:
            motion_ex_payload = {
                "front_wheels_angle": self._motion_ex.front_wheels_angle,
                "local_velocity": [
                    self._motion_ex.local_velocity_x,
                    self._motion_ex.local_velocity_y,
                    self._motion_ex.local_velocity_z,
                ],
                "wheel_speed": self._motion_ex.wheel_speed,
                "wheel_slip_ratio": self._motion_ex.wheel_slip_ratio,
                "wheel_slip_angle": self._motion_ex.wheel_slip_angle,
                "wheel_lat_force": self._motion_ex.wheel_lat_force,
                "wheel_long_force": self._motion_ex.wheel_long_force,
                "wheel_vert_force": self._motion_ex.wheel_vert_force,
            }

        participants_payload: dict[str, Any] = {}
        if self._participants is not None and self._lap_data is not None:
            lap = self._safe_indexed(self._lap_data.car_lap_data, self._player_idx)
            ahead_name: str | None = None
            behind_name: str | None = None
            if lap is not None:
                player_position = lap.car_position
                for idx, other_lap in enumerate(self._lap_data.car_lap_data):
                    if other_lap.car_position == player_position - 1:
                        ahead_name = self._participant_name(idx)
                    if other_lap.car_position == player_position + 1:
                        behind_name = self._participant_name(idx)
            player_name = self._participant_name(self._player_idx)
            participants_payload = {
                "num_active_cars": self._participants.num_active_cars,
                "player_name": player_name,
                "ahead_driver": ahead_name,
                "behind_driver": behind_name,
            }

        events_payload = {
            "latest_code": self._event.event_string_code if self._event is not None else None,
            "recent_codes": [event.event_string_code for event in list(self._event_log)[-8:]],
        }

        history_payload: dict[str, Any] = {}
        player_history = self._session_history.get(self._player_idx)
        if player_history is not None:
            best_lap_ms = None
            if player_history.best_lap_time_lap_num > 0:
                best_idx = player_history.best_lap_time_lap_num - 1
                best_lap = self._safe_indexed(player_history.lap_history_data, best_idx)
                if best_lap is not None:
                    best_lap_ms = best_lap.lap_time_in_ms
            history_payload = {
                "num_laps": player_history.num_laps,
                "num_tyre_stints": player_history.num_tyre_stints,
                "best_lap_time_lap_num": player_history.best_lap_time_lap_num,
                "best_lap_time_ms": best_lap_ms,
            }

        tyre_sets_payload: dict[str, Any] = {}
        if self._tyre_sets is not None:
            fitted = self._safe_indexed(self._tyre_sets.tyre_set_data, self._tyre_sets.fitted_idx)
            tyre_sets_payload = {
                "car_idx": self._tyre_sets.car_idx,
                "fitted_idx": self._tyre_sets.fitted_idx,
                "fitted_compound": fitted.visual_tyre_compound if fitted is not None else None,
                "available_sets": sum(1 for tyre in self._tyre_sets.tyre_set_data if tyre.available),
            }

        time_trial_payload: dict[str, Any] = {}
        if self._time_trial is not None:
            time_trial_payload = {
                "player_lap_ms": self._time_trial.player_session.lap_time_in_ms,
                "personal_best_ms": self._time_trial.personal_best.lap_time_in_ms,
                "rival_best_ms": self._time_trial.rival.lap_time_in_ms,
            }

        final_classification_payload: dict[str, Any] = {}
        if self._final_classification is not None:
            player_result = self._safe_indexed(
                self._final_classification.classification_data,
                self._player_idx,
            )
            if player_result is not None:
                final_classification_payload = {
                    "position": player_result.position,
                    "points": player_result.points,
                    "num_laps": player_result.num_laps,
                    "best_lap_time_ms": player_result.best_lap_time_in_ms,
                    "num_pit_stops": player_result.num_pit_stops,
                }

        lap_positions_payload: dict[str, Any] = {}
        if self._lap_positions is not None:
            latest_positions = (
                self._lap_positions.position_for_vehicle_idx[-1]
                if self._lap_positions.position_for_vehicle_idx
                else []
            )
            lap_positions_payload = {
                "num_laps": self._lap_positions.num_laps,
                "lap_start": self._lap_positions.lap_start,
                "latest_player_position": (
                    latest_positions[self._player_idx]
                    if latest_positions and self._player_idx < len(latest_positions)
                    else None
                ),
            }

        lobby_payload: dict[str, Any] = {}
        if self._lobby_info is not None:
            lobby_payload = {
                "num_players": self._lobby_info.num_players,
                "player_names": [p.name for p in self._lobby_info.lobby_players[:10]],
            }

        available_sections = [
            name
            for name, data in (
                ("gap", gap),
                ("car_state", car_state),
                ("health", health),
                ("session", session_payload),
                ("setup", setup_payload),
                ("motion", motion_payload),
                ("motion_ex", motion_ex_payload),
                ("participants", participants_payload),
                ("events", events_payload),
                ("session_history", history_payload),
                ("tyre_sets", tyre_sets_payload),
                ("time_trial", time_trial_payload),
                ("final_classification", final_classification_payload),
                ("lap_positions", lap_positions_payload),
                ("lobby", lobby_payload),
            )
            if data
        ]

        return {
            "available": bool(available_sections),
            "available_sections": available_sections,
            "gap": gap,
            "car_state": car_state,
            "health": health,
            "session": session_payload,
            "setup": setup_payload,
            "motion": motion_payload,
            "motion_ex": motion_ex_payload,
            "participants": participants_payload,
            "events": events_payload,
            "session_history": history_payload,
            "tyre_sets": tyre_sets_payload,
            "time_trial": time_trial_payload,
            "final_classification": final_classification_payload,
            "lap_positions": lap_positions_payload,
            "lobby": lobby_payload,
        }

    def _record_radio_line(self, speaker: str, text: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return
        line = f"{speaker}: {cleaned}"
        if self._conversation_history:
            last_line = self._conversation_history[-1]
            if line.lower() == last_line.lower():
                return
            _, _, last_text = last_line.partition(":")
            if cleaned.lower() == last_text.strip().lower():
                return
        self._conversation_history.append(line)

    def _build_radio_history_context(self) -> str:
        if not self._conversation_history:
            return "No prior exchanges."
        return "\n".join(self._conversation_history)

    def _update_driver_preference(self, query_text: str) -> None:
        lowered = (query_text or "").strip().lower()
        if not lowered:
            return
        if any(token in lowered for token in ("dumb it down", "simpler", "simple terms", "keep it simple")):
            self._driver_preference = "simple"
            return
        if any(token in lowered for token in ("more detail", "explain deeper", "full detail")):
            self._driver_preference = "detailed"

    def _driver_preference_instruction(self) -> str:
        if self._driver_preference == "simple":
            return (
                "Driver preference: keep technical explanations simple and plain language until they ask for more detail."
            )
        if self._driver_preference == "detailed":
            return (
                "Driver preference: provide slightly more technical detail when giving strategy or setup guidance."
            )
        return "Driver preference: standard race-radio clarity."

    async def _rewrite_in_character(
        self,
        *,
        draft_answer: str,
        driver_query: str,
        persona: str,
        tone_instruction_text: str,
        conversation_context: str,
    ) -> str | None:
        """Prompt-driven rewrite pass when response drifts out of character."""
        if not self.client.available:
            return None

        rewrite_system_prompt = (
            "You are rewriting race radio text. "
            "Stay fully in character as a real human race engineer teammate. "
            "Never mention AI/model/policy limitations or inability statements. "
            "Return plain text only in 1-2 short radio sentences, direct to the driver. "
            f"Persona: {persona}. "
            f"{tone_instruction_text} "
            "This is an ongoing conversation; do not reset with greetings."
        )
        rewrite_user_prompt = (
            f"Driver message: {driver_query}\n"
            f"Conversation memory:\n{conversation_context}\n\n"
            f"Draft answer to fix:\n{draft_answer}\n\n"
            "Rewrite the draft so it sounds natural, in-character, and useful."
        )
        rewritten = await self.client.generate_text(rewrite_system_prompt, rewrite_user_prompt)
        if not rewritten:
            return None
        rewritten_brief = to_radio_brief(rewritten, max_sentences=2, max_chars=175)
        if not rewritten_brief or is_out_of_character_response(rewritten_brief):
            return None
        return rewritten_brief

    async def _handle_query(self, query: DriverQuery):
        """When the driver asks a question, consult configured LLM using full context."""
        logger.info(f"LLM Advisor received query: '{query.query}'")
        self._record_radio_line("Driver", query.query)
        self._update_driver_preference(query.query)

        if not self.latest_telemetry:
            await self._send_insight(
                "I don't have any telemetry data yet. Stand by.",
                "info",
                record_dialogue=True,
            )
            return

        context = self._build_context()
        detected_tone = detect_driver_tone(query.query)
        strategy_criticality = (
            self.latest_strategy.criticality if self.latest_strategy is not None else None
        )
        strategy_critical = bool(strategy_criticality is not None and strategy_criticality >= 4)
        persona = choose_engineer_persona(
            detected_tone,
            rapport_level=self._rapport_level,
            strategy_criticality=strategy_criticality,
            speed_kph=self.latest_telemetry.speed if self.latest_telemetry is not None else None,
            lap=self.latest_telemetry.lap if self.latest_telemetry is not None else None,
        )
        if persona != self._active_persona:
            logger.info("advisor persona switched %s -> %s", self._active_persona, persona)
        self._active_persona = persona
        style_instruction = tone_instruction(
            detected_tone,
            rapport_level=self._rapport_level,
            strategy_critical=strategy_critical,
        )
        self._rapport_level = next_rapport_level(self._rapport_level, detected_tone)

        try:
            reply: EngineerReply = await self._agent.answer(
                query=query.query,
                telemetry_context=context,
                persona_name=persona.replace("_", " "),
                persona_instruction=persona_instruction(persona),
                tone_instruction=style_instruction,
                driver_preference_instruction=self._driver_preference_instruction(),
            )
            brief_answer = to_radio_brief(
                reply.radio_text,
                max_sentences=2,
                max_chars=190 if detected_tone == "banter" else 170,
            )
            if brief_answer:
                if is_out_of_character_response(brief_answer):
                    logger.warning(
                        "advisor reply drifted out of character; attempting prompt-based rewrite."
                    )
                    rewritten = await self._rewrite_in_character(
                        draft_answer=brief_answer,
                        driver_query=query.query,
                        persona=persona.replace("_", " "),
                        tone_instruction_text=style_instruction,
                        conversation_context=self._build_radio_history_context(),
                    )
                    brief_answer = (
                        rewritten
                        if rewritten
                        else "Copy. I'm with you. Keep the call coming."
                    )

                styled_answer = apply_persona_fillers(
                    brief_answer,
                    persona=persona,
                    tone=detected_tone,
                    strategy_critical=strategy_critical,
                    rapport_level=self._rapport_level,
                )
                styled_answer = to_radio_brief(
                    styled_answer,
                    max_sentences=2,
                    max_chars=190 if detected_tone == "banter" else 175,
                )
                insight_type = (
                    "warning"
                    if strategy_critical or detected_tone == "urgent"
                    else reply.insight_type
                )
                priority = (
                    5
                    if strategy_critical or detected_tone == "urgent"
                    else int(reply.priority)
                )
                await self._send_insight(
                    styled_answer,
                    insight_type,
                    priority=priority,
                    record_dialogue=True,
                )

        except Exception as e:
            logger.error(f"Failed to generate advisor response: {e}")
            await self._send_insight(
                "I'm having trouble with the data connection.",
                "warning",
                priority=5,
                record_dialogue=True,
            )

    async def _send_insight(
        self,
        message: str,
        insight_type: str,
        priority: int = 3,
        *,
        record_dialogue: bool = False,
    ):
        insight = DrivingInsight(message=message, type=insight_type, priority=priority)
        if record_dialogue:
            self._record_radio_line("Becca", message)
        await bus.publish("driving_insight", insight)


# Backward compatibility alias.
LLMAdvisor = RaceEngineerService



