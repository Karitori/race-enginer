from typing import TypedDict

from utils.telemetry_enums import TRACK_NAMES


class TrackStrategyProfile(TypedDict):
    name: str
    overtake_difficulty: float
    pit_loss_ms: int
    undercut_bias: float
    weather_volatility: float


_DEFAULT_PROFILE: TrackStrategyProfile = {
    "name": "Unknown",
    "overtake_difficulty": 0.55,
    "pit_loss_ms": 21500,
    "undercut_bias": 1.0,
    "weather_volatility": 0.5,
}

# Heuristic track tendencies tuned for F1-like racecraft.
# Values are not intended as exact real-world timing measurements.
_TRACK_PROFILES: dict[int, TrackStrategyProfile] = {
    0: {  # Melbourne
        "name": "Melbourne",
        "overtake_difficulty": 0.58,
        "pit_loss_ms": 21800,
        "undercut_bias": 1.03,
        "weather_volatility": 0.45,
    },
    2: {  # Shanghai
        "name": "Shanghai",
        "overtake_difficulty": 0.42,
        "pit_loss_ms": 20500,
        "undercut_bias": 0.96,
        "weather_volatility": 0.4,
    },
    3: {  # Sakhir
        "name": "Sakhir",
        "overtake_difficulty": 0.38,
        "pit_loss_ms": 22800,
        "undercut_bias": 0.94,
        "weather_volatility": 0.25,
    },
    4: {  # Catalunya
        "name": "Catalunya",
        "overtake_difficulty": 0.63,
        "pit_loss_ms": 21400,
        "undercut_bias": 1.05,
        "weather_volatility": 0.4,
    },
    5: {  # Monaco
        "name": "Monaco",
        "overtake_difficulty": 0.97,
        "pit_loss_ms": 24000,
        "undercut_bias": 1.15,
        "weather_volatility": 0.2,
    },
    6: {  # Montreal
        "name": "Montreal",
        "overtake_difficulty": 0.36,
        "pit_loss_ms": 19800,
        "undercut_bias": 0.95,
        "weather_volatility": 0.55,
    },
    7: {  # Silverstone
        "name": "Silverstone",
        "overtake_difficulty": 0.46,
        "pit_loss_ms": 21000,
        "undercut_bias": 0.97,
        "weather_volatility": 0.75,
    },
    9: {  # Hungaroring
        "name": "Hungaroring",
        "overtake_difficulty": 0.84,
        "pit_loss_ms": 21400,
        "undercut_bias": 1.1,
        "weather_volatility": 0.35,
    },
    10: {  # Spa
        "name": "Spa",
        "overtake_difficulty": 0.45,
        "pit_loss_ms": 23000,
        "undercut_bias": 0.98,
        "weather_volatility": 0.78,
    },
    11: {  # Monza
        "name": "Monza",
        "overtake_difficulty": 0.3,
        "pit_loss_ms": 19700,
        "undercut_bias": 0.9,
        "weather_volatility": 0.3,
    },
    12: {  # Singapore
        "name": "Singapore",
        "overtake_difficulty": 0.8,
        "pit_loss_ms": 22300,
        "undercut_bias": 1.08,
        "weather_volatility": 0.65,
    },
    13: {  # Suzuka
        "name": "Suzuka",
        "overtake_difficulty": 0.66,
        "pit_loss_ms": 21200,
        "undercut_bias": 1.04,
        "weather_volatility": 0.5,
    },
    14: {  # Abu Dhabi
        "name": "Abu Dhabi",
        "overtake_difficulty": 0.42,
        "pit_loss_ms": 20600,
        "undercut_bias": 0.95,
        "weather_volatility": 0.15,
    },
    15: {  # Austin
        "name": "Austin",
        "overtake_difficulty": 0.48,
        "pit_loss_ms": 21200,
        "undercut_bias": 0.97,
        "weather_volatility": 0.45,
    },
    16: {  # Interlagos
        "name": "Interlagos",
        "overtake_difficulty": 0.43,
        "pit_loss_ms": 19100,
        "undercut_bias": 0.93,
        "weather_volatility": 0.65,
    },
    17: {  # Austria
        "name": "Red Bull Ring",
        "overtake_difficulty": 0.35,
        "pit_loss_ms": 18600,
        "undercut_bias": 0.9,
        "weather_volatility": 0.4,
    },
    19: {  # Mexico City
        "name": "Mexico City",
        "overtake_difficulty": 0.4,
        "pit_loss_ms": 20200,
        "undercut_bias": 0.94,
        "weather_volatility": 0.35,
    },
    20: {  # Baku
        "name": "Baku",
        "overtake_difficulty": 0.34,
        "pit_loss_ms": 20800,
        "undercut_bias": 0.92,
        "weather_volatility": 0.35,
    },
    26: {  # Zandvoort
        "name": "Zandvoort",
        "overtake_difficulty": 0.86,
        "pit_loss_ms": 22300,
        "undercut_bias": 1.1,
        "weather_volatility": 0.55,
    },
    27: {  # Imola
        "name": "Imola",
        "overtake_difficulty": 0.81,
        "pit_loss_ms": 22000,
        "undercut_bias": 1.08,
        "weather_volatility": 0.45,
    },
    29: {  # Jeddah
        "name": "Jeddah",
        "overtake_difficulty": 0.41,
        "pit_loss_ms": 20300,
        "undercut_bias": 0.94,
        "weather_volatility": 0.3,
    },
    30: {  # Miami
        "name": "Miami",
        "overtake_difficulty": 0.5,
        "pit_loss_ms": 20900,
        "undercut_bias": 0.98,
        "weather_volatility": 0.5,
    },
    31: {  # Las Vegas
        "name": "Las Vegas",
        "overtake_difficulty": 0.32,
        "pit_loss_ms": 20500,
        "undercut_bias": 0.9,
        "weather_volatility": 0.2,
    },
    32: {  # Losail
        "name": "Losail",
        "overtake_difficulty": 0.39,
        "pit_loss_ms": 21400,
        "undercut_bias": 0.95,
        "weather_volatility": 0.35,
    },
}


def get_track_strategy_profile(track_id: int) -> TrackStrategyProfile:
    profile = _TRACK_PROFILES.get(track_id)
    if profile:
        return profile

    fallback_name = TRACK_NAMES.get(track_id, _DEFAULT_PROFILE["name"])
    return {
        **_DEFAULT_PROFILE,
        "name": fallback_name,
    }

