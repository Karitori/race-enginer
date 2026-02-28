import logging
from race_engineer.core.event_bus import bus
from race_engineer.telemetry.models import TelemetryTick, DrivingInsight

logger = logging.getLogger(__name__)

class PerformanceAnalyzer:
    """
    Analyzes incoming telemetry data to detect performance issues and opportunities.
    """
    def __init__(self):
        # Subscribe to telemetry ticks
        bus.subscribe("telemetry_tick", self._handle_telemetry_tick)

        # Basic state tracking
        self.last_lap = 0
        self.tire_warning_issued = False

    async def _handle_telemetry_tick(self, data: TelemetryTick):
        """Processes a single telemetry frame."""
        # Lap detection
        if data.lap > self.last_lap:
            self.last_lap = data.lap
            self.tire_warning_issued = False  # Reset per lap or stint
            logger.info(f"Feedback Engine: Detected new lap {self.last_lap}.")
            
            insight = DrivingInsight(
                message=f"Lap {self.last_lap} started. Keep the momentum going.",
                type="encouragement",
                priority=2
            )
            await bus.publish("driving_insight", insight)

        # Brake point check
        if data.brake > 0.8 and data.speed > 250:
            logger.info("Feedback Engine: Hard braking detected.")
            insight = DrivingInsight(
                message="Watch the lockup, you are braking very hard into this zone.",
                type="warning",
                priority=4
            )
            await bus.publish("driving_insight", insight)

        # Tire wear check
        max_wear = max(data.tire_wear_fl, data.tire_wear_fr, data.tire_wear_rl, data.tire_wear_rr)
        if max_wear > 60.0 and not self.tire_warning_issued:
            logger.info(f"Feedback Engine: High tire wear detected ({max_wear}%).")
            self.tire_warning_issued = True
            insight = DrivingInsight(
                message=f"Tires are heavily worn. You might want to consider boxing in the next few laps.",
                type="strategy",
                priority=5
            )
            await bus.publish("driving_insight", insight)
