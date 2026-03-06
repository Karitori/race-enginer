from typing import Any

STRATEGY_ANALYST_SYSTEM_PROMPT = (
    "You are the lead strategy analyst for an F1 team. "
    "Use telemetry aggregates and risk flags to produce concise, actionable race guidance."
)


def build_strategy_prompt(snapshot: dict[str, Any], risks: list[str]) -> str:
    return (
        "Telemetry snapshot:\n"
        f"{snapshot}\n\n"
        "Detected risks:\n"
        f"{risks}\n\n"
        "Return exactly two lines:\n"
        "Summary: <short analysis>\n"
        "Recommendation: <action for driver>"
    )

