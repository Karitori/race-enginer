from __future__ import annotations

import ast
import json
import re
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.graph.message import add_messages

from models.engineer_agent import EngineerPlan, EngineerReply
from prompts.race_engineer_prompts import build_advisor_system_prompt
from services.llm_factory import ChatClient
from utils.radio_character_guard import is_out_of_character_response
from utils.radio_text import to_radio_brief


class RaceEngineerGraphState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    telemetry_context: str
    persona_name: str
    persona_instruction: str
    tone_instruction: str
    driver_preference_instruction: str
    plan: dict[str, Any]
    tool_payload: dict[str, Any] | None
    final_reply: dict[str, Any]


_GAP_MARKERS = (
    "gap",
    "leader",
    "ahead",
    "behind",
    "delta",
    "position",
    "where am i",
)
_CAR_STATE_MARKERS = (
    "fuel",
    "ers",
    "battery",
    "drs",
    "tyre age",
    "tire age",
    "compound",
)
_HEALTH_MARKERS = (
    "damage",
    "temps",
    "temperature",
    "brake temp",
    "tire temp",
    "tyre temp",
    "overheating",
    "health",
)
_FULL_SNAPSHOT_MARKERS = (
    "weather",
    "rain",
    "wind",
    "setup",
    "wing",
    "differential",
    "suspension",
    "history",
    "best lap",
    "session history",
    "participants",
    "who is ahead",
    "who's ahead",
    "who is behind",
    "who's behind",
    "events",
    "incident",
    "classification",
    "lobby",
    "lap positions",
    "full telemetry",
    "full snapshot",
)
_SOCIAL_MARKERS = (
    "how are you",
    "how's it going",
    "tell me about yourself",
    "tell me more about yourself",
    "who are you",
    "radio check",
    "hello",
    "hey",
    "yo",
    "drinks",
    "joke",
)

_PLAN_SYSTEM_PROMPT = (
    "You classify race-radio driver requests. "
    "Return only JSON matching the schema. "
    "Choose telemetry tools only when the driver asks for live metrics. "
    "Valid tool names: none, telemetry_gap, telemetry_car_state, telemetry_health, telemetry_full_snapshot."
)


def _to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text")
                if value:
                    parts.append(str(value))
        return " ".join(parts)
    return str(content)


def _latest_driver_message(messages: list[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return _to_text(message.content).strip()
    return ""


def _conversation_context(messages: list[AnyMessage], max_lines: int = 8) -> str:
    lines: list[str] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            text = _to_text(message.content).strip()
            if text:
                lines.append(f"Driver: {text}")
        elif isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            text = _to_text(message.content).strip()
            if text:
                lines.append(f"Becca: {text}")
    if not lines:
        return "No prior exchanges."
    return "\n".join(lines[-max_lines:])


def _heuristic_tool_name(query: str) -> str:
    lowered = (query or "").strip().lower()
    if not lowered:
        return "none"
    has_gap = any(marker in lowered for marker in _GAP_MARKERS)
    has_car_state = any(marker in lowered for marker in _CAR_STATE_MARKERS)
    has_health = any(marker in lowered for marker in _HEALTH_MARKERS)
    has_full = any(marker in lowered for marker in _FULL_SNAPSHOT_MARKERS)
    if has_gap:
        return "telemetry_gap"
    if has_car_state:
        return "telemetry_car_state"
    if has_health:
        return "telemetry_health"
    if has_full:
        return "telemetry_full_snapshot"
    if any(marker in lowered for marker in _SOCIAL_MARKERS):
        return "none"
    return "none"


def _tool_intent_from_name(tool_name: str) -> str:
    if tool_name == "none":
        return "general"
    return "telemetry"


def _coerce_tool_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        merged = " ".join(str(item) for item in content)
        return {"raw": merged}
    text = str(content or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        return {"raw": parsed}
    except Exception:
        pass
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, dict):
            return parsed
        return {"raw": parsed}
    except Exception:
        return {"raw": text}


def _sanitize_radio_text(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^\s*becca\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    if re.match(
        r"^\s*(?:becca\s*:\s*)?driver latest message\s*:",
        cleaned,
        flags=re.IGNORECASE,
    ):
        return ""
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def make_plan_node(planner_client: ChatClient):
    async def plan_node(state: RaceEngineerGraphState) -> dict[str, Any]:
        messages = state.get("messages", [])
        query = _latest_driver_message(messages)

        heuristic_tool = _heuristic_tool_name(query)
        if heuristic_tool == "none" and any(
            marker in (query or "").strip().lower() for marker in _SOCIAL_MARKERS
        ):
            return {
                "plan": EngineerPlan(
                    intent="general",
                    needs_tool=False,
                    tool_name="none",
                ).model_dump()
            }
        if heuristic_tool != "none":
            plan = EngineerPlan(
                intent="telemetry",
                needs_tool=True,
                tool_name=heuristic_tool,
            )
            return {"plan": plan.model_dump()}

        if planner_client.available and query:
            structured = await planner_client.generate_structured(
                system_prompt=_PLAN_SYSTEM_PROMPT,
                user_prompt=f"Driver query: {query}",
                schema=EngineerPlan,
            )
            if isinstance(structured, EngineerPlan):
                return {"plan": structured.model_dump()}
            if isinstance(structured, dict):
                try:
                    plan = EngineerPlan.model_validate(structured)
                    return {"plan": plan.model_dump()}
                except Exception:
                    pass

        plan = EngineerPlan(
            intent=_tool_intent_from_name("none"),
            needs_tool=False,
            tool_name="none",
        )
        return {"plan": plan.model_dump()}

    return plan_node


def route_after_plan(state: RaceEngineerGraphState) -> str:
    raw_plan = state.get("plan") or {}
    try:
        plan = EngineerPlan.model_validate(raw_plan)
    except Exception:
        return "respond"
    if plan.needs_tool and plan.tool_name != "none":
        return "tool"
    return "respond"


def build_tool_call_node(state: RaceEngineerGraphState) -> dict[str, Any]:
    raw_plan = state.get("plan") or {}
    try:
        plan = EngineerPlan.model_validate(raw_plan)
    except Exception:
        return {}
    if not plan.needs_tool or plan.tool_name == "none":
        return {}
    tool_call = {
        "name": plan.tool_name,
        "args": {},
        "id": f"tool_{plan.tool_name}",
        "type": "tool_call",
    }
    return {"messages": [AIMessage(content="", tool_calls=[tool_call])]}


def capture_tool_payload_node(state: RaceEngineerGraphState) -> dict[str, Any]:
    messages = state.get("messages", [])
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            return {
                "tool_payload": {
                    "tool_name": message.name or "",
                    "payload": _coerce_tool_content(message.content),
                }
            }
    return {"tool_payload": None}


def make_respond_node(reply_client: ChatClient):
    async def respond_node(state: RaceEngineerGraphState) -> dict[str, Any]:
        messages = state.get("messages", [])
        query = _latest_driver_message(messages)
        raw_plan = state.get("plan") or {}
        tool_payload_wrapper = state.get("tool_payload") or {}
        tool_name = str(tool_payload_wrapper.get("tool_name") or "")
        tool_payload = tool_payload_wrapper.get("payload")

        try:
            plan = EngineerPlan.model_validate(raw_plan)
        except Exception:
            plan = EngineerPlan()

        final: EngineerReply | None = None
        if reply_client.available:
            conversation_context = _conversation_context(messages)
            system_prompt = build_advisor_system_prompt(
                telemetry_context=state.get("telemetry_context", "No telemetry data available yet."),
                persona_name=state.get("persona_name", "focused teammate"),
                persona_instruction=state.get("persona_instruction", ""),
                tone_instruction=state.get("tone_instruction", ""),
                conversation_context=conversation_context,
                driver_preference_instruction=state.get(
                    "driver_preference_instruction",
                    "Driver preference: standard race-radio clarity.",
                ),
            )

            tool_context = tool_payload if isinstance(tool_payload, dict) else {}
            user_prompt = (
                "<driver_query>\n"
                f"{query}\n"
                "</driver_query>\n"
                "<conversation_memory>\n"
                f"{conversation_context}\n"
                "</conversation_memory>\n"
                "<telemetry_tool_context>\n"
                f"{json.dumps(tool_context, ensure_ascii=True)}\n"
                "</telemetry_tool_context>\n"
                "<response_instruction>\n"
                "Reply as Becca with only the final race-radio content.\n"
                "</response_instruction>"
            )

            final = EngineerReply(
                radio_text="Copy. I'm with you. Keep the car tidy.",
                insight_type="info",
                priority=4,
            )

            structured = await reply_client.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=EngineerReply,
            )
            if isinstance(structured, EngineerReply):
                final = structured
            elif isinstance(structured, dict):
                try:
                    final = EngineerReply.model_validate(structured)
                except Exception:
                    final = None
            else:
                text = await reply_client.generate_text(system_prompt, user_prompt)
                if text:
                    final = EngineerReply(
                        radio_text=text,
                        insight_type="warning" if plan.intent == "urgent" else "info",
                        priority=5 if plan.intent == "urgent" else 4,
                    )

        if final is None:
            final = EngineerReply(
                radio_text="Copy. I'm with you. Keep the car tidy.",
                insight_type="info",
                priority=4,
            )

        safe_text = _sanitize_radio_text(final.radio_text)
        safe_text = to_radio_brief(safe_text, max_sentences=2, max_chars=175)
        if not safe_text or is_out_of_character_response(safe_text):
            safe_text = "Copy. I'm with you. Keep the car tidy."

        final_reply = EngineerReply(
            radio_text=safe_text,
            insight_type=final.insight_type,
            priority=final.priority,
        )
        return {
            "final_reply": final_reply.model_dump(),
            "messages": [AIMessage(content=final_reply.radio_text)],
        }

    return respond_node
