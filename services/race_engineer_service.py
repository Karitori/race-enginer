import logging
from collections import deque
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

    def _build_driver_prompt(self, driver_query: str) -> str:
        return (
            f"Driver latest message: {driver_query}\n\n"
            "Conversation memory (most recent at bottom):\n"
            f"{self._build_radio_history_context()}\n\n"
            "Reply as Becca on live race radio."
        )

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
                record_dialogue=True,
            )
            return

        system_prompt = build_advisor_system_prompt(
            telemetry_context=context,
            persona_name=persona.replace("_", " "),
            persona_instruction=persona_instruction(persona),
            tone_instruction=style_instruction,
            conversation_context=self._build_radio_history_context(),
            driver_preference_instruction=self._driver_preference_instruction(),
        )
        user_prompt = self._build_driver_prompt(query.query)

        try:
            answer = await self.client.generate_text(system_prompt, user_prompt)
            if answer:
                brief_answer = to_radio_brief(
                    answer,
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
                    insight_type = "warning" if strategy_critical or detected_tone == "urgent" else "info"
                    priority = 5 if strategy_critical or detected_tone == "urgent" else 4
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



