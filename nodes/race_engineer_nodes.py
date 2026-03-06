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

_PLAN_SYSTEM_PROMPT = (
    "You classify race-radio driver requests. "
    "Return only JSON matching the schema. "
    "Choose telemetry tools only when the driver asks for live metrics. "
    "Valid tool names: none, telemetry_gap, telemetry_car_state, telemetry_health."
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
    if any(marker in lowered for marker in _GAP_MARKERS):
        return "telemetry_gap"
    if any(marker in lowered for marker in _CAR_STATE_MARKERS):
        return "telemetry_car_state"
    if any(marker in lowered for marker in _HEALTH_MARKERS):
        return "telemetry_health"
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


def _s(value: Any) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return v / 1000.0


def _deterministic_gap_reply(payload: dict[str, Any]) -> EngineerReply:
    if not payload.get("available"):
        return EngineerReply(
            radio_text="Gap data is unstable this second. Keep pushing, I will call it as soon as it settles.",
            insight_type="info",
            priority=3,
        )

    lap = payload.get("lap")
    position = payload.get("position")
    gap_leader_s = _s(payload.get("gap_leader_ms"))
    gap_front_s = _s(payload.get("gap_front_ms"))

    parts: list[str] = []
    if position:
        if lap:
            parts.append(f"You are P{int(position)} on lap {int(lap)}")
        else:
            parts.append(f"You are P{int(position)}")

    if position == 1:
        parts.append("you are leading")
    elif gap_leader_s is not None:
        parts.append(f"gap to leader is {gap_leader_s:.1f} seconds")

    if position and int(position) > 1 and gap_front_s is not None:
        parts.append(f"{gap_front_s:.1f} to the car ahead")

    line = ", ".join(parts).strip()
    if not line:
        line = "No reliable gap value available right now."
    return EngineerReply(
        radio_text=f"{line}.",
        insight_type="info",
        priority=4,
    )


def _deterministic_car_state_reply(payload: dict[str, Any]) -> EngineerReply:
    if not payload.get("available"):
        return EngineerReply(
            radio_text="Car-state feed is unstable this second. Stand by for the next clean sample.",
            insight_type="info",
            priority=3,
        )

    fuel_laps = payload.get("fuel_remaining_laps")
    ers_pct = payload.get("ers_pct")
    drs_available = payload.get("drs_available")
    tyre_age = payload.get("tyre_age_laps")
    compound = payload.get("compound")

    parts: list[str] = []
    if fuel_laps is not None:
        parts.append(f"fuel {float(fuel_laps):.1f} laps")
    if ers_pct is not None:
        parts.append(f"ERS {float(ers_pct):.0f} percent")
    if compound:
        if tyre_age is not None:
            parts.append(f"{compound} tyres age {int(tyre_age)} laps")
        else:
            parts.append(f"{compound} tyres")
    parts.append("DRS available" if drs_available else "DRS not available")

    line = ", ".join(parts).strip() or "No clean car-state values available right now."
    return EngineerReply(
        radio_text=f"{line}.",
        insight_type="info",
        priority=4,
    )


def _deterministic_health_reply(payload: dict[str, Any]) -> EngineerReply:
    if not payload.get("available"):
        return EngineerReply(
            radio_text="Health feed is unstable this second. Keep it tidy while I refresh the data.",
            insight_type="info",
            priority=3,
        )

    max_brake = payload.get("max_brake_temp_c")
    max_tire = payload.get("max_tire_surface_temp_c")
    max_damage = payload.get("max_damage_pct")
    damage_component = payload.get("max_damage_component")

    parts: list[str] = []
    critical = False
    if max_brake is not None:
        parts.append(f"max brake temp {int(max_brake)} C")
        if float(max_brake) >= 900:
            critical = True
    if max_tire is not None:
        parts.append(f"max tyre surface {int(max_tire)} C")
        if float(max_tire) >= 112:
            critical = True
    if max_damage is not None and max_damage_component:
        parts.append(f"{damage_component} damage {int(max_damage)} percent")
        if float(max_damage) >= 45:
            critical = True

    line = ", ".join(parts).strip() or "No major health issues flagged right now."
    return EngineerReply(
        radio_text=f"{line}.",
        insight_type="warning" if critical else "info",
        priority=5 if critical else 4,
    )


def _deterministic_tool_reply(
    tool_name: str,
    payload: dict[str, Any] | None,
) -> EngineerReply | None:
    data = payload or {}
    if tool_name == "telemetry_gap":
        return _deterministic_gap_reply(data)
    if tool_name == "telemetry_car_state":
        return _deterministic_car_state_reply(data)
    if tool_name == "telemetry_health":
        return _deterministic_health_reply(data)
    return None


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

        deterministic = _deterministic_tool_reply(tool_name or plan.tool_name, tool_payload)
        if deterministic is not None:
            final = deterministic
        else:
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
                f"Driver latest message: {query}\n\n"
                "Conversation memory (most recent at bottom):\n"
                f"{conversation_context}\n\n"
                f"Telemetry tool context: {json.dumps(tool_context, ensure_ascii=True)}\n\n"
                "Reply as Becca on live race radio."
            )

            final = EngineerReply(
                radio_text="Copy. I'm with you. Keep the car tidy.",
                insight_type="info",
                priority=4,
            )

            if reply_client.available:
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
                        pass
                else:
                    text = await reply_client.generate_text(system_prompt, user_prompt)
                    if text:
                        final = EngineerReply(
                            radio_text=text,
                            insight_type="warning" if plan.intent == "urgent" else "info",
                            priority=5 if plan.intent == "urgent" else 4,
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

