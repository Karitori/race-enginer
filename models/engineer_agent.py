from typing import Literal

from pydantic import BaseModel, Field


TelemetryToolName = Literal[
    "none",
    "telemetry_gap",
    "telemetry_car_state",
    "telemetry_health",
    "telemetry_full_snapshot",
]
EngineerIntent = Literal[
    "telemetry",
    "strategy",
    "social",
    "banter",
    "urgent",
    "general",
]
EngineerInsightType = Literal["info", "warning", "encouragement", "strategy"]


class EngineerPlan(BaseModel):
    intent: EngineerIntent = "general"
    needs_tool: bool = False
    tool_name: TelemetryToolName = "none"


class EngineerReply(BaseModel):
    radio_text: str = Field(..., min_length=1, description="Final race-radio line.")
    insight_type: EngineerInsightType = "info"
    priority: int = Field(4, ge=1, le=5)
