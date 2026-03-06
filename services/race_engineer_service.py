import os
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
from utils.radio_context import build_radio_context

logger = logging.getLogger(__name__)


class RaceEngineerService:
    """
    Acts as the brain of the Race Engineer.
    Maintains the latest telemetry state from expanded packets and uses the configured LLM
    to answer driver queries dynamically with full race context.
    """

    def __init__(self):
        provider = os.getenv("ADVISOR_PROVIDER") or os.getenv("LLM_PROVIDER")
        model = os.getenv("ADVISOR_MODEL") or os.getenv("LLM_MODEL")
        self.client = ChatClient(provider=provider, model=model, temperature=0.3)

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
        """When the driver asks a question, consult Gemini using full race context."""
        logger.info(f"LLM Advisor received query: '{query.query}'")

        if not self.latest_telemetry:
            await self._send_insight(
                "I don't have any telemetry data yet. Stand by.", "info"
            )
            return

        context = self._build_context()

        if not self.client.available:
            logger.warning("advisor LLM not configured. Using fallback dynamic response.")
            t = self.latest_telemetry
            fallback_msg = f"I'm offline, but I see your front left tire is at {t.tire_wear_fl:.1f} percent."
            await self._send_insight(fallback_msg, "info")
            return

        system_prompt = (
            "You are an F1 Race Engineer speaking directly over the radio to your driver. "
            "Give detailed, thorough answers. Be conversational but informative. "
            "Use the provided live telemetry to answer the driver's question accurately. "
            "You have access to tire wear, fuel levels, ERS state, weather, position, "
            "damage status, and strategy team analysis. "
            f"Live Telemetry Context: {context}"
        )

        try:
            answer = await self.client.generate_text(system_prompt, query.query)
            if answer:
                await self._send_insight(answer.strip(), "info", priority=4)

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



