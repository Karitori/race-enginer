import asyncio
import logging
import math
import random
from typing import Any, Dict

from race_engineer.core.event_bus import bus
from race_engineer.telemetry.models import TelemetryTick

logger = logging.getLogger(__name__)

class BaseTelemetryParser:
    """
    Simulates realistic live UDP telemetry data. 
    In a real implementation, this would read from a socket (e.g., F1 23 UDP format).
    """
    def __init__(self):
        self._is_running = False

    async def start(self):
        self._is_running = True
        logger.info("Telemetry Parser (Simulated) started.")
        await self._listen_loop()

    def stop(self):
        self._is_running = False
        logger.info("Telemetry Parser stopped.")

    async def _listen_loop(self):
        """Generates dynamic, plausible lap data at 20Hz."""
        lap = 1
        track_pos = 0.0
        # Initialize tire wear (increases slightly every tick)
        wear_fl, wear_fr, wear_rl, wear_rr = 5.0, 5.0, 5.0, 5.0
        
        # Track characteristics (corners at specific percentages of the track)
        corners = [0.15, 0.35, 0.50, 0.80, 0.90]

        while self._is_running:
            await asyncio.sleep(0.05) # 20 ticks per second (typical F1 UDP rate ranges 20-60Hz)
            
            # Move the car forward
            base_speed_delta = 0.001
            track_pos += base_speed_delta
            
            # Lap completion logic
            if track_pos >= 1.0:
                track_pos = 0.0
                lap += 1
                
            # Sector logic
            sector = 1
            if track_pos > 0.33: sector = 2
            if track_pos > 0.66: sector = 3

            # Calculate distance to nearest corner
            dist_to_corner = min([abs(track_pos - c) for c in corners])
            
            # Physics Mock
            if dist_to_corner < 0.03:
                # Braking Zone / Apex
                speed = 110.0 + random.uniform(-10, 10)
                gear = 3
                throttle = 0.1
                brake = 0.9 + random.uniform(0, 0.1)
                rpm = 7500 + random.randint(-500, 500)
                steering = 0.8 * (1 if track_pos > 0.5 else -1) # Turning
            elif dist_to_corner < 0.08:
                # Acceleration Zone
                speed = 220.0 + random.uniform(-15, 15)
                gear = 5
                throttle = 0.8
                brake = 0.0
                rpm = 10500 + random.randint(-500, 500)
                steering = 0.2
            else:
                # Straight
                speed = 315.0 + random.uniform(-5, 5)
                gear = 8
                throttle = 1.0
                brake = 0.0
                rpm = 11800 + random.randint(-200, 200)
                steering = 0.0
                
            # Tire Wear (accelerates during braking and cornering)
            wear_rate = 0.0005 if brake > 0.5 else 0.0001
            wear_fl += wear_rate * 1.1 # Front left takes more wear
            wear_fr += wear_rate
            wear_rl += wear_rate * 1.5 # Rear left takes heavy exit wear
            wear_rr += wear_rate * 1.3
            
            try:
                packet = TelemetryTick(
                    speed=speed,
                    gear=gear,
                    throttle=throttle,
                    brake=brake,
                    steering=steering,
                    engine_rpm=rpm,
                    tire_wear_fl=wear_fl,
                    tire_wear_fr=wear_fr,
                    tire_wear_rl=wear_rl,
                    tire_wear_rr=wear_rr,
                    lap=lap,
                    track_position=track_pos,
                    sector=sector
                )
                
                # Process and publish normalized telemetry tick
                await bus.publish("telemetry_tick", packet)
            except Exception as e:
                logger.error(f"Failed to publish telemetry packet: {e}")
