import asyncio
import logging
from typing import Any

from langgraph.graph import StateGraph, END

from db.contracts import TelemetryRepository
from models.strategy import StrategyInsight
from nodes.strategy_analysis_nodes import (
    StrategyState,
    make_collect_metrics_node,
    make_detect_risks_node,
    make_recommend_action_node,
)
from services.event_bus_service import bus

logger = logging.getLogger(__name__)


class StrategyAgent:
    """LangGraph strategy agent that connects strategy nodes end-to-end."""

    def __init__(self, repository: TelemetryRepository, poll_interval: int = 15):
        self.repository = repository
        self.poll_interval = poll_interval
        self._is_running = False

        # Placeholder for provider-agnostic LLM runner hook.
        self._llm_runner = None

        graph = StateGraph(StrategyState)
        graph.add_node("collect_metrics", make_collect_metrics_node(self.repository))
        graph.add_node("detect_risks", make_detect_risks_node())
        graph.add_node("recommend_action", make_recommend_action_node(self._llm_runner))

        graph.set_entry_point("collect_metrics")
        graph.add_edge("collect_metrics", "detect_risks")
        graph.add_edge("detect_risks", "recommend_action")
        graph.add_edge("recommend_action", END)
        self._graph = graph.compile()

    async def start(self) -> None:
        self._is_running = True
        logger.info("LangGraph strategy engine started.")

        while self._is_running:
            await asyncio.sleep(self.poll_interval)
            await self._run_once()

    def stop(self) -> None:
        self._is_running = False

    async def _run_once(self) -> None:
        try:
            state: dict[str, Any] = await self._graph.ainvoke({})
            summary = state.get("summary")
            recommendation = state.get("recommendation")
            criticality = int(state.get("criticality", 2))

            if not summary or not recommendation:
                return

            insight = StrategyInsight(
                summary=summary,
                recommendation=recommendation,
                criticality=criticality,
            )
            await bus.publish("strategy_insight", insight)
            logger.info("LangGraph strategy insight published: %s", summary)

        except Exception as exc:
            logger.error("LangGraph strategy engine run failed: %s", exc)



