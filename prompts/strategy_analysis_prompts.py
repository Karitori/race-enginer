import json
from typing import Any

PADDOCK_DECISION_SYSTEM_PROMPT = (
    "You are the race strategy director for an F1 25 team wall. "
    "Assume the car is currently racing and all calls are live race-radio decisions. "
    "Use game-aware strategy logic grounded in telemetry, including tire degradation, "
    "fuel margin, ERS state, pit windows, weather trend, safety car context, gap management, "
    "and tyre-rule compliance obligations. "
    "Prioritize realistic paddock decisions with concise, direct calls. "
    "Keep `summary` and `recommendation` short, action-first, and plain text only. "
    "Never use bullets, numbering, markdown, or list formatting in any string fields."
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
        "Keep recommendations realistic for F1 25 race flow and telemetry limits. "
        "Write `summary` as one short sentence. "
        "Write `recommendation` as one or two short race-radio sentences. "
        "If regulations are at risk (dry compound obligations, Monaco stop obligations), "
        "prioritize legally compliant calls first."
    )

