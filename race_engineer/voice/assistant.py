import logging
import asyncio
from typing import Dict, Any

from race_engineer.core.event_bus import bus
from race_engineer.telemetry.models import DrivingInsight, DriverQuery

logger = logging.getLogger(__name__)

# Try to import pyttsx3, fallback to mock if not available (e.g. headless CI)
try:
    import pyttsx3 # type: ignore
    HAS_TTS = True
except ImportError:
    HAS_TTS = False
    logger.warning("pyttsx3 not installed. Voice output will be mocked.")

class VoiceAssistant:
    """
    Handles two-way communication with the driver using Text-to-Speech (TTS)
    and Speech-to-Text (STT).
    """
    def __init__(self):
        # Listen for generated insights to broadcast to the driver
        bus.subscribe("driving_insight", self._announce_insight)
        
        self.tts_engine: Any = None
        
        global HAS_TTS
        if HAS_TTS:
            import pyttsx3 # type: ignore
            try:
                # Type ignored because we conditionally import
                self.tts_engine = pyttsx3.init() # type: ignore
                self.tts_engine.setProperty('rate', 170) # type: ignore
                # Set a male/female voice if desired (skipping for general compatibility)
            except Exception as e:
                logger.error(f"Failed to initialize pyttsx3: {e}")
                HAS_TTS = False

    async def _announce_insight(self, insight: DrivingInsight):
        """Text-to-Speech handler for incoming insights."""
        logger.info(f"VOICE ENGINE [{insight.type.upper()}] (Pri {insight.priority}): TTS '{insight.message}'")
        
        if self.tts_engine is not None and HAS_TTS:
            # Run pyttsx3 in an executor to avoid blocking the asyncio event loop
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._speak_sync, insight.message)
            
    def _speak_sync(self, message: str):
        """Synchronous method to run the pyttsx3 engine."""
        try:
            if self.tts_engine is not None:
                self.tts_engine.say(message) # type: ignore
                self.tts_engine.runAndWait() # type: ignore
        except Exception as e:
            logger.error(f"TTS Error: {e}")

    async def listen_for_driver(self):
        """
        Speech-to-Text loop listening to driver input via microphone.
        """
        while True:
            # Mock driver input wait loop
            await asyncio.sleep(5.0)
            
            # e.g. "What is my tire wear?"
            query = DriverQuery(
                query="How's the tire wear?",
                confidence=0.95
            )
            logger.info(f"Driver said: '{query.query}'")
            
            # Publish driver's intent to the bus
            await bus.publish("driver_query", query)
