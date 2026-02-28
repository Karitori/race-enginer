import os
import asyncio
import logging
from google import genai
from google.genai import types

from race_engineer.core.event_bus import bus
from race_engineer.data.store import DataStore
from race_engineer.intelligence.models import StrategyInsight

logger = logging.getLogger(__name__)

class StrategyTeamWorker:
    """
    A background AI agent representing the "Analyst Team".
    It constantly queries the DuckDB DataStore, analyzes historical trends,
    and publishes StrategyInsights for the Race Engineer to use.
    """
    def __init__(self, datastore: DataStore, poll_interval: int = 15):
        self.datastore = datastore
        self.poll_interval = poll_interval # seconds
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None
        self._is_running = False

    async def start(self):
        """Starts the background worker loop."""
        self._is_running = True
        logger.info("Strategy Team Analyst background agent started.")
        await self._worker_loop()

    def stop(self):
        self._is_running = False

    async def _worker_loop(self):
        while self._is_running:
            await asyncio.sleep(self.poll_interval)
            await self._analyze_telemetry_trends()

    async def _analyze_telemetry_trends(self):
        """
        Runs analytical SQL queries against the DataStore, then
        feeds the results to Gemini to generate strategic advice.
        """
        # Step 1: Run analytical queries
        try:
            # Query 1: Max tire wear per lap (to see degradation curve)
            wear_query = """
                SELECT lap, 
                       MAX(tire_wear_fl) as max_wear_fl, 
                       MAX(tire_wear_rr) as max_wear_rr 
                FROM telemetry 
                GROUP BY lap 
                ORDER BY lap DESC 
                LIMIT 3
            """
            
            # Note: query() blocks, so we run it in an executor so we don't stall the event bus
            loop = asyncio.get_running_loop()
            recent_wear = await loop.run_in_executor(None, self.datastore.query, wear_query)
            
            if not recent_wear:
                return # Not enough data yet

            # Format data for LLM
            data_summary = "Recent Laps Tire Wear (Lap, FL%, RR%):\n"
            for row in recent_wear:
                # row is a tuple like (12, 15.5, 14.2)
                data_summary += f"- Lap {row[0]}: Front-Left {row[1]:.1f}%, Rear-Right {row[2]:.1f}%\n"

            logger.info("Strategy Team generated data summary, invoking Analyst AI...")

            # Step 2: Use LLM to analyze the data
            if not self.client:
                # Fallback if no API key
                fallback_insight = StrategyInsight(
                    summary="Tire wear data collected.",
                    recommendation="Continue current pace.",
                    criticality=2
                )
                await bus.publish("strategy_insight", fallback_insight)
                return

            system_instruction = (
                "You are the Lead Strategy Analyst for an F1 team. "
                "You review raw database aggregates and provide a short strategic summary and recommendation "
                "to the Race Engineer. "
                "Your output must be EXACTLY two lines:\n"
                "Line 1: 'Summary: <your analysis>'\n"
                "Line 2: 'Recommendation: <what the driver should do>'"
            )

            response = await self.client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=data_summary,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                    max_output_tokens=100
                )
            )
            
            text = response.text
            if not text:
                return

            # Parse the response (rudimentary parsing)
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            summary = lines[0].replace("Summary:", "").strip() if len(lines) > 0 else "Analysis complete."
            rec = lines[1].replace("Recommendation:", "").strip() if len(lines) > 1 else "Keep pushing."

            # Determine criticality based on keywords
            criticality = 3
            if "box" in rec.lower() or "critical" in summary.lower():
                criticality = 5

            insight = StrategyInsight(
                summary=summary,
                recommendation=rec,
                criticality=criticality
            )
            
            logger.info(f"Strategy Team published insight: {summary}")
            await bus.publish("strategy_insight", insight)

        except Exception as e:
            logger.error(f"Strategy Team analysis failed: {e}")
