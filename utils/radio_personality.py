from typing import Literal

DriverTone = Literal["banter", "frustrated", "urgent", "neutral"]

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

