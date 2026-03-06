from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from models.engineer_agent import EngineerReply
from nodes.race_engineer_nodes import (
    RaceEngineerGraphState,
    build_tool_call_node,
    capture_tool_payload_node,
    make_plan_node,
    make_respond_node,
    route_after_plan,
)
from services.llm_factory import ChatClient
from tools.telemetry_tools import get_engineer_tools, set_telemetry_tool_provider

logger = logging.getLogger(__name__)


class RaceEngineerAgent:
    """Stateful LangGraph agent for race-radio answers with telemetry tool access."""

    def __init__(self, *, telemetry_provider: Any, thread_id: str):
        self._thread_id = thread_id
        self._planner_client = ChatClient(role="advisor", temperature=0.6)
        self._reply_client = ChatClient(role="advisor", temperature=0.6)
        set_telemetry_tool_provider(telemetry_provider)
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(RaceEngineerGraphState)
        tool_node = ToolNode(get_engineer_tools())

        graph.add_node("plan", make_plan_node(self._planner_client))
        graph.add_node("build_tool_call", build_tool_call_node)
        graph.add_node("run_tool", tool_node)
        graph.add_node("capture_tool_payload", capture_tool_payload_node)
        graph.add_node("respond", make_respond_node(self._reply_client))

        graph.add_edge(START, "plan")
        graph.add_conditional_edges(
            "plan",
            route_after_plan,
            {
                "tool": "build_tool_call",
                "respond": "respond",
            },
        )
        graph.add_edge("build_tool_call", "run_tool")
        graph.add_edge("run_tool", "capture_tool_payload")
        graph.add_edge("capture_tool_payload", "respond")
        graph.add_edge("respond", END)

        return graph.compile(checkpointer=InMemorySaver())

    async def answer(
        self,
        *,
        query: str,
        telemetry_context: str,
        persona_name: str,
        persona_instruction: str,
        tone_instruction: str,
        driver_preference_instruction: str,
    ) -> EngineerReply:
        state_input: RaceEngineerGraphState = {
            "messages": [HumanMessage(content=query)],
            "telemetry_context": telemetry_context,
            "persona_name": persona_name,
            "persona_instruction": persona_instruction,
            "tone_instruction": tone_instruction,
            "driver_preference_instruction": driver_preference_instruction,
        }
        config = {"configurable": {"thread_id": self._thread_id}}
        state = await self._graph.ainvoke(state_input, config=config)

        raw = state.get("final_reply")
        if isinstance(raw, EngineerReply):
            return raw
        if isinstance(raw, dict):
            try:
                return EngineerReply.model_validate(raw)
            except Exception:
                pass
        logger.warning("race engineer agent produced no structured reply; using fallback")
        return EngineerReply(
            radio_text="Copy. Keep pushing, I am with you.",
            insight_type="info",
            priority=4,
        )

