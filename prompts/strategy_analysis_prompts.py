import json
from typing import Any

PADDOCK_DECISION_SYSTEM_PROMPT = (
    "You are the race strategy director for an F1 25 team wall. "
    "Use game-aware strategy logic grounded in telemetry, including tire degradation, "
    "fuel margin, ERS state, pit windows, weather trend, safety car context, and gap management. "
    "Prioritize realistic paddock decisions with concise, direct calls."
)


def build_paddock_decision_prompt(
    snapshot: dict[str, Any],
    team_calls: list[dict[str, Any]],
    deterministic_decision: dict[str, Any],
) -> str:
    payload = {
        "snapshot": snapshot,
        "team_calls": team_calls,
        "deterministic_decision": deterministic_decision,
    }
    return (
        "Given this strategy state, refine the race-wall decision.\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Use structured output for the strategy decision schema. "
        "Keep recommendations realistic for F1 25 race flow and telemetry limits."
    )

