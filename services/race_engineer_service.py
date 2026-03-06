import logging
from typing import Optional

from models.strategy import StrategyInsight
from models.telemetry import TelemetryTick, DriverQuery, DrivingInsight
from models.telemetry_packets import (
    PacketCarStatusData,
    PacketCarDamageData,
    PacketSessionData,
    PacketLapData,
)
from services.event_bus_service import bus
from services.llm_factory import ChatClient
from prompts.race_engineer_prompts import build_advisor_system_prompt
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

        # State tracking (legacy)
        self.latest_telemetry: Optional[TelemetryTick] = None
        self.latest_strategy: Optional[StrategyInsight] = None

        # Expanded state tracking
        self._car_status: Optional[PacketCarStatusData] = None
        self._car_damage: Optional[PacketCarDamageData] = None
        self._session: Optional[PacketSessionData] = None
        self._lap_data: Optional[PacketLapData] = None
        self._player_idx: int = 0

        # Subscribe to data
        bus.subscribe("telemetry_tick", self._update_telemetry)
        bus.subscribe("strategy_insight", self._update_strategy)
        bus.subscribe("driver_query", self._handle_query)
        bus.subscribe("packet_car_status", self._update_car_status)
        bus.subscribe("packet_car_damage", self._update_car_damage)
        bus.subscribe("packet_session", self._update_session)
        bus.subscribe("packet_lap_data", self._update_lap_data)

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

    async def _handle_query(self, query: DriverQuery):
        """When the driver asks a question, consult configured LLM using full context."""
        logger.info(f"LLM Advisor received query: '{query.query}'")

        if not self.latest_telemetry:
            await self._send_insight(
                "I don't have any telemetry data yet. Stand by.", "info"
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

        if not self.client.available:
            logger.warning("advisor LLM not configured. Using fallback dynamic response.")
            t = self.latest_telemetry
            fallback_msg = f"I'm offline, but I see your front left tire is at {t.tire_wear_fl:.1f} percent."
            fallback_msg = apply_persona_fillers(
                fallback_msg,
                persona=persona,
                tone=detected_tone,
                strategy_critical=strategy_critical,
                rapport_level=self._rapport_level,
            )
            await self._send_insight(
                to_radio_brief(fallback_msg, max_sentences=2, max_chars=150),
                "info",
            )
            return

        system_prompt = build_advisor_system_prompt(
            telemetry_context=context,
            persona_name=persona.replace("_", " "),
            persona_instruction=persona_instruction(persona),
            tone_instruction=style_instruction,
        )

        try:
            answer = await self.client.generate_text(system_prompt, query.query)
            if answer:
                brief_answer = to_radio_brief(
                    answer,
                    max_sentences=2,
                    max_chars=190 if detected_tone == "banter" else 170,
                )
                if brief_answer:
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
                    insight_type = "warning" if strategy_critical or detected_tone == "urgent" else "info"
                    priority = 5 if strategy_critical or detected_tone == "urgent" else 4
                    await self._send_insight(styled_answer, insight_type, priority=priority)

        except Exception as e:
            logger.error(f"Failed to generate advisor response: {e}")
            await self._send_insight(
                "I'm having trouble with the data connection.", "warning", priority=5
            )

    async def _send_insight(self, message: str, insight_type: str, priority: int = 3):
        insight = DrivingInsight(message=message, type=insight_type, priority=priority)
        await bus.publish("driving_insight", insight)


# Backward compatibility alias.
LLMAdvisor = RaceEngineerService



