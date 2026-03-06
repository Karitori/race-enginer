from pydantic import BaseModel, Field


class VoiceSummaryDecision(BaseModel):
    escalate: bool = Field(
        ...,
        description="Whether the queue contains content worth speaking now.",
    )
    tts_text: str = Field(
        "",
        description="Final radio sentence to speak; empty when escalate is false.",
    )

