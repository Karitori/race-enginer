import asyncio
import logging
import time
from typing import Any

from langgraph.graph import StateGraph, END

from db.contracts import TelemetryRepository
from models.strategy import StrategyInsight
from prompts.strategy_analysis_prompts import (
    PADDOCK_DECISION_SYSTEM_PROMPT,
    build_paddock_decision_prompt,
)
from nodes.strategy_analysis_nodes import (
    LLMRunner,
    StrategyState,
    make_collect_metrics_node,
    make_tire_wall_node,
    make_energy_wall_node,
    make_race_control_node,
    make_regulations_node,
    make_strategy_wall_node,
    make_racecraft_node,
    make_synthesize_decision_node,
)
from services.event_bus_service import bus
from services.llm_factory import ChatClient

logger = logging.getLogger(__name__)


class StrategyAgent:
    """LangGraph strategy agent that connects strategy nodes end-to-end."""

    def __init__(self, repository: TelemetryRepository, poll_interval: int = 15):
        self.repository = repository
        self.poll_interval = poll_interval
        self._is_running = False
        self._current_poll_interval = float(poll_interval)
        self._last_signature: str | None = None
        self._last_publish_monotonic = 0.0

        self._client = ChatClient(role="strategy", temperature=0.15)
        self._llm_runner = self._build_llm_runner()

        graph = StateGraph(StrategyState)
        graph.add_node("collect_metrics", make_collect_metrics_node(self.repository))
        graph.add_node("tire_wall", make_tire_wall_node())
        graph.add_node("energy_wall", make_energy_wall_node())
        graph.add_node("race_control", make_race_control_node())
        graph.add_node("regulations", make_regulations_node())
        graph.add_node("strategy_wall", make_strategy_wall_node())
        graph.add_node("racecraft", make_racecraft_node())
        graph.add_node("synthesize", make_synthesize_decision_node(self._llm_runner))

        graph.set_entry_point("collect_metrics")
        graph.add_edge("collect_metrics", "tire_wall")
        graph.add_edge("tire_wall", "energy_wall")
        graph.add_edge("energy_wall", "race_control")
        graph.add_edge("race_control", "regulations")
        graph.add_edge("regulations", "strategy_wall")
        graph.add_edge("strategy_wall", "racecraft")
        graph.add_edge("racecraft", "synthesize")
        graph.add_edge("synthesize", END)
        self._graph = graph.compile()

    def _build_llm_runner(self) -> LLMRunner | None:
        if not self._client.available:
            logger.info("strategy LLM not configured; using deterministic paddock logic.")
            return None

        async def _runner(
            snapshot: dict[str, Any],
            calls: list[dict[str, Any]],
            deterministic: dict[str, Any],
        ) -> dict[str, Any] | None:
            prompt = build_paddock_decision_prompt(snapshot, calls, deterministic)
            structured = await self._client.generate_structured(
                system_prompt=PADDOCK_DECISION_SYSTEM_PROMPT,
                user_prompt=prompt,
                schema=StrategyInsight,
            )
            if structured is None:
                return None
            if isinstance(structured, StrategyInsight):
                return structured.model_dump()
            if isinstance(structured, dict):
                return structured
            return None

        return _runner

    async def start(self) -> None:
        self._is_running = True
        logger.info("LangGraph strategy agent started.")

        while self._is_running:
            await self._run_once()
            await asyncio.sleep(self._current_poll_interval)

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
                confidence=float(state.get("confidence", 0.5)),
                risk_tags=list(state.get("risk_tags", [])),
                pit_call=state.get("pit_call"),
                fuel_call=state.get("fuel_call"),
                ers_call=state.get("ers_call"),
                team_notes=list(state.get("team_notes", [])),
            )
            self._current_poll_interval = self._poll_interval_for_criticality(
                insight.criticality
            )

            if self._should_publish(insight):
                await bus.publish("strategy_insight", insight)
                logger.info(
                    "Strategy insight published (C%d, poll %.1fs): %s",
                    insight.criticality,
                    self._current_poll_interval,
                    summary,
                )
            else:
                logger.debug(
                    "Strategy insight suppressed (duplicate/too-frequent): %s", summary
                )

        except Exception as exc:
            logger.error("LangGraph strategy agent run failed: %s", exc)

    def _poll_interval_for_criticality(self, criticality: int) -> float:
        if criticality >= 5:
            return max(4.0, self.poll_interval * 0.35)
        if criticality >= 4:
            return max(5.0, self.poll_interval * 0.5)
        if criticality == 3:
            return max(8.0, self.poll_interval * 0.75)
        return float(self.poll_interval)

    def _should_publish(self, insight: StrategyInsight) -> bool:
        signature = "|".join(
            [
                insight.summary.strip().lower(),
                insight.recommendation.strip().lower(),
                str(insight.criticality),
                ",".join(sorted(insight.risk_tags)),
            ]
        )
        now = time.monotonic()

        if self._last_signature is None:
            self._last_signature = signature
            self._last_publish_monotonic = now
            return True

        if insight.criticality >= 4 and signature != self._last_signature:
            self._last_signature = signature
            self._last_publish_monotonic = now
            return True

        min_interval = 12.0 if insight.criticality <= 2 else 8.0
        if signature != self._last_signature and (now - self._last_publish_monotonic) >= min_interval:
            self._last_signature = signature
            self._last_publish_monotonic = now
            return True

        heartbeat_interval = 60.0
        if (
            insight.criticality >= 3
            and (now - self._last_publish_monotonic) >= heartbeat_interval
        ):
            self._last_signature = signature
            self._last_publish_monotonic = now
            return True

        return False



