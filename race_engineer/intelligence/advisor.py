import os
import logging
from typing import Optional

from google import genai
from google.genai import types

from race_engineer.core.event_bus import bus
from race_engineer.telemetry.models import TelemetryTick, DriverQuery, DrivingInsight

logger = logging.getLogger(__name__)

class LLMAdvisor:
    """
    Acts as the brain of the Race Engineer.
    Maintains the latest telemetry state and uses Gemini to answer driver queries dynamically.
    """
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None
        
        # State tracking
        self.latest_telemetry: Optional[TelemetryTick] = None
        
        # Subscribe to data
        bus.subscribe("telemetry_tick", self._update_telemetry)
        bus.subscribe("driver_query", self._handle_query)

    async def _update_telemetry(self, tick: TelemetryTick):
        """Keep the latest telemetry in memory to provide context to the LLM."""
        self.latest_telemetry = tick

    async def _handle_query(self, query: DriverQuery):
        """When the driver asks a question, consult Gemini using the latest telemetry."""
        logger.info(f"LLM Advisor received query: '{query.query}'")
        
        if not self.latest_telemetry:
            # We don't have data yet
            await self._send_insight("I don't have any telemetry data yet. Stand by.", "info")
            return

        # Prepare the context from the latest telemetry
        t = self.latest_telemetry
        context = (
            f"Speed: {t.speed}km/h, Gear: {t.gear}, RPM: {t.engine_rpm}, "
            f"Lap: {t.lap}, Sector: {t.sector}, "
            f"Tire Wear - FL:{t.tire_wear_fl:.1f}%, FR:{t.tire_wear_fr:.1f}%, "
            f"RL:{t.tire_wear_rl:.1f}%, RR:{t.tire_wear_rr:.1f}%"
        )

        if not self.client:
            logger.warning("GEMINI_API_KEY not set. Using fallback dynamic response.")
            # Fallback if no API key is provided, still using real data instead of static string
            fallback_msg = f"I'm offline, but I see your front left tire is at {t.tire_wear_fl} percent."
            await self._send_insight(fallback_msg, "info")
            return

        # Construct the prompt
        system_prompt = (
            "You are an F1 Race Engineer speaking directly over the radio to your driver. "
            "Keep your answers extremely concise (under 20 words) and conversational. "
            "Use the provided live telemetry to answer the driver's question accurately. "
            f"Live Telemetry Context: {context}"
        )

        try:
            response = await self.client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=query.query,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.3,
                    max_output_tokens=50
                )
            )
            
            answer = response.text
            if answer:
                await self._send_insight(answer.strip(), "info", priority=4)
                
        except Exception as e:
            logger.error(f"Failed to generate Gemini response: {e}")
            await self._send_insight("I'm having trouble with the data connection.", "warning", priority=5)

    async def _send_insight(self, message: str, insight_type: str, priority: int = 3):
        """Helper to publish the generated insight."""
        insight = DrivingInsight(
            message=message,
            type=insight_type,
            priority=priority
        )
        await bus.publish("driving_insight", insight)
