from typing import Literal

DriverTone = Literal["banter", "frustrated", "urgent", "neutral"]
EngineerPersona = Literal[
    "pitwall_commander",
    "calm_coach",
    "dry_wit_teammate",
    "strategist",
    "focused_teammate",
]

_BANTER_MARKERS = (
    "haha",
    "lol",
    "lmao",
    "joke",
    "kidding",
    "roast",
    "banter",
)
_FRUSTRATION_MARKERS = (
    "wtf",
    "damn",
    "cant",
    "can't",
    "struggling",
    "useless",
    "annoying",
    "frustrated",
)
_URGENCY_MARKERS = (
    "now",
    "immediately",
    "urgent",
    "help",
    "what do i do",
    "problem",
    "issue",
    "broken",
    "damage",
    "spinning",
    "puncture",
)

def detect_driver_tone(query: str) -> DriverTone:
    text = (query or "").strip().lower()
    if not text:
        return "neutral"

    if any(marker in text for marker in _URGENCY_MARKERS):
        return "urgent"
    if any(marker in text for marker in _FRUSTRATION_MARKERS):
        return "frustrated"
    if any(marker in text for marker in _BANTER_MARKERS):
        return "banter"
    return "neutral"


def next_rapport_level(current: int, tone: DriverTone) -> int:
    """Keep a tiny memory of rapport to make personality feel less robotic."""
    level = max(0, min(5, int(current)))
    if tone == "banter":
        return min(5, level + 1)
    if tone in {"urgent", "frustrated"}:
        return max(0, level - 1)
    return level


def choose_engineer_persona(
    tone: DriverTone,
    *,
    rapport_level: int,
    strategy_criticality: int | None,
    speed_kph: float | None,
    lap: int | None,
) -> EngineerPersona:
    """Automatically select a race engineer personality from race context."""
    critical = strategy_criticality is not None and strategy_criticality >= 4
    if critical or tone == "urgent":
        return "pitwall_commander"
    if tone == "frustrated":
        return "calm_coach"
    if tone == "banter" and rapport_level >= 2:
        return "dry_wit_teammate"
    if strategy_criticality is not None and strategy_criticality >= 3:
        return "strategist"
    if lap is not None and lap <= 2:
        return "strategist"
    if speed_kph is not None and speed_kph >= 290:
        return "strategist"
    return "focused_teammate"


def persona_instruction(persona: EngineerPersona) -> str:
    if persona == "pitwall_commander":
        return (
            "Persona: pit wall commander. Crisp, authoritative calls. "
            "No fluff, no jokes, immediate execution language."
        )
    if persona == "calm_coach":
        return (
            "Persona: calm coach. Keep the driver composed under pressure with short, steady language."
        )
    if persona == "dry_wit_teammate":
        return (
            "Persona: dry-wit teammate. Light witty acknowledgement allowed, then immediate race action."
        )
    if persona == "strategist":
        return (
            "Persona: strategist. Tactical and precise, still concise and radio-natural."
        )
    return (
        "Persona: focused teammate. Human, direct, and confident with practical race-radio rhythm."
    )


def apply_persona_fillers(
    text: str,
    *,
    persona: EngineerPersona,
    tone: DriverTone,
    strategy_critical: bool,
    rapport_level: int,
) -> str:
    """Light-touch rhythm shaping without hardcoded lexical fillers."""
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned

    # Keep wording model-driven; only add punctuation emphasis for urgent calls.
    if strategy_critical or tone == "urgent":
        if cleaned[-1] not in ".!?":
            return f"{cleaned}!"
    return cleaned


def tone_instruction(
    tone: DriverTone,
    *,
    rapport_level: int,
    strategy_critical: bool,
) -> str:
    if strategy_critical or tone == "urgent":
        return (
            "Tone mode: urgent. No jokes. Give immediate command-first call, "
            "then one short reason."
        )
    if tone == "frustrated":
        return (
            "Tone mode: calm support. Be steady, confident, and direct. "
            "Acknowledge pressure briefly, no humor."
        )
    if tone == "banter":
        if rapport_level >= 2:
            return (
                "Tone mode: light banter. Open with a very short witty line (max 6 words), "
                "then give the driving call. Keep it teammate-like, never mocking."
            )
        return (
            "Tone mode: friendly. You can lightly acknowledge humor, then give direct advice."
        )
    return (
        "Tone mode: composed teammate. Sound human and direct, with concise race-radio phrasing."
    )
