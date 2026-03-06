import logging
import os
from collections import deque
from typing import Any, Optional

from agents.race_engineer_agent import RaceEngineerAgent
from models.engineer_agent import EngineerReply
from models.strategy import StrategyInsight
from models.telemetry import TelemetryTick, DriverQuery, DrivingInsight
from models.telemetry_packets import (
    PacketCarStatusData,
    PacketCarDamageData,
    PacketSessionData,
    PacketLapData,
    PacketCarTelemetryData,
)
from services.event_bus_service import bus
from services.llm_factory import ChatClient
from utils.telemetry_enums import TYRE_COMPOUND_SHORT
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



