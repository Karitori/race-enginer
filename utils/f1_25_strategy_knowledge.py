from utils.telemetry_enums import TYRE_COMPOUND_NAMES

# F1 25 telemetry/game-domain thresholds used by strategy nodes.
# These are heuristics for race-engineering decisions, not strict sim rules.

CRITICAL_TIRE_WEAR_PCT = 78.0
HIGH_TIRE_WEAR_PCT = 70.0
SAFETY_CAR_PIT_WEAR_THRESHOLD_PCT = 45.0
DEGRADATION_RISING_PCT_PER_SAMPLE = 0.35

RAIN_TO_INTERMEDIATE_PCT = 50
RAIN_TO_WET_PCT = 75
RAIN_ALERT_PCT = 55
RAIN_HEAVY_PCT = 70
RAIN_TREND_ALERT_DELTA = 20

FUEL_CRITICAL_BUFFER_LAPS = 0.7
FUEL_LOW_BUFFER_LAPS = 1.8

ERS_LOW_PCT = 12.0
ERS_ATTACK_PCT = 65.0
OVERTAKE_GAP_MS = 1300
AGGRESSIVE_OVERTAKE_GAP_MS = 900

PACE_DROP_ALERT_MS = 350.0


def compound_name(compound_code: int) -> str:
    return TYRE_COMPOUND_NAMES.get(compound_code, f"compound-{compound_code}")


def recommend_next_compound(current_compound: int, rain_pct: int, laps_remaining: int) -> int:
    """Heuristic next-compound selector for common F1 25 race scenarios."""
    if rain_pct >= RAIN_TO_WET_PCT:
        return 8  # Wet
    if rain_pct >= RAIN_TO_INTERMEDIATE_PCT:
        return 7  # Intermediate

    # Late-race attack preference on dry conditions.
    if laps_remaining <= 12:
        if current_compound in (18, 17):
            return 16  # Soft
        return 17

    # Mid-race durability preference.
    if current_compound == 16:
        return 18  # Soft -> Hard
    if current_compound == 17:
        return 18  # Medium -> Hard
    if current_compound == 18:
        return 17  # Hard -> Medium
    return 17

