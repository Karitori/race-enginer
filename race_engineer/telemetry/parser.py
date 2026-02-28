import asyncio
import logging
from typing import Any, Dict

from race_engineer.core.event_bus import bus
from race_engineer.telemetry.models import TelemetryTick

logger = logging.getLogger(__name__)

class BaseTelemetryParser:
    """
    Reads telemetry data from a source (UDP stream, file, etc.)
    and publishes standardized events.
    """
    def __init__(self):
        self._is_running = False

    async def start(self):
        """Starts the telemetry parser loop."""
        self._is_running = True
        logger.info("Telemetry Parser started.")
        await self._listen_loop()

    def stop(self):
        """Stops the telemetry parser."""
        self._is_running = False
        logger.info("Telemetry Parser stopped.")

    async def _listen_loop(self):
        """
        The main loop that ingests data. Must be overridden by subclasses.
        Normally this would listen to a UDP socket.
        """
        while self._is_running:
            # Mock delay
            await asyncio.sleep(1.0)
            
            # Simulated incoming telemetry packet
            try:
                mock_packet = TelemetryTick(
                    speed=280.0,
                    gear=8,
                    throttle=1.0,
                    brake=0.0,
                    steering=0.0,
                    engine_rpm=11500,
                    tire_wear_fl=15.0,
                    tire_wear_fr=16.5,
                    tire_wear_rl=14.0,
                    tire_wear_rr=14.5,
                    lap=12,
                    track_position=0.45,
                    sector=2
                )
                
                # Process and publish normalized telemetry tick
                await bus.publish("telemetry_tick", mock_packet)
            except Exception as e:
                logger.error(f"Failed to parse telemetry packet: {e}")
