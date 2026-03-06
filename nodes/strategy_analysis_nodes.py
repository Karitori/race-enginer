import asyncio
from typing import Any, Awaitable, Callable, TypedDict

from db.contracts import TelemetryRepository
from tools.strategy_snapshot_tool import build_strategy_snapshot_tool


class StrategyState(TypedDict, total=False):
    snapshot: dict[str, Any]
    risks: list[str]
    summary: str
    recommendation: str
    criticality: int


LLMRunner = Callable[[dict[str, Any], list[str]], Awaitable[tuple[str, str]]]


def make_collect_metrics_node(repository: TelemetryRepository):
    snapshot_tool = build_strategy_snapshot_tool(repository)

    async def _collect_metrics_node(state: StrategyState) -> StrategyState:
        loop = asyncio.get_running_loop()
        snapshot = await loop.run_in_executor(None, lambda: snapshot_tool.invoke({}))
        if not isinstance(snapshot, dict):
            snapshot = {}
        return {**state, "snapshot": snapshot}

    return _collect_metrics_node


def make_detect_risks_node():
    async def _detect_risks_node(state: StrategyState) -> StrategyState:
        risks: list[str] = []
        snapshot = state.get("snapshot", {})

        wear = snapshot.get("tire_wear")
        if wear:
            max_wear = max(float(w) for w in wear)
            if max_wear >= 70:
                risks.append(f"Critical tire wear at {max_wear:.1f}%")
            elif max_wear >= 55:
                risks.append(f"Elevated tire wear at {max_wear:.1f}%")

        fuel = snapshot.get("fuel")
        if fuel:
            fuel_laps = float(fuel[1])
            if fuel_laps <= 2.5:
                risks.append(f"Fuel critical: {fuel_laps:.1f} laps remaining")
            elif fuel_laps <= 5.0:
                risks.append(f"Fuel low: {fuel_laps:.1f} laps remaining")

        weather = snapshot.get("weather")
        if weather:
            rain_pct = int(weather[3])
            if rain_pct >= 50:
                risks.append(f"Rain risk rising: {rain_pct}%")

        lap = snapshot.get("lap")
        if lap:
            gap_front = int(lap[1])
            if 0 < gap_front <= 1000:
                risks.append(f"Overtake chance: front gap {gap_front/1000:.3f}s")

        return {**state, "risks": risks}

    return _detect_risks_node


def make_recommend_action_node(llm_runner: LLMRunner | None = None):
    async def _recommend_action_node(state: StrategyState) -> StrategyState:
        risks = state.get("risks", [])
        snapshot = state.get("snapshot", {})

        if llm_runner:
            summary, recommendation = await llm_runner(snapshot, risks)
        else:
            if not snapshot:
                summary = "No telemetry snapshot available yet."
                recommendation = "Hold current approach and wait for stable telemetry."
            elif any("Critical tire wear" in r for r in risks):
                summary = "Tire degradation is now critical."
                recommendation = "Box this lap and switch to a durable compound."
            elif any("Fuel critical" in r for r in risks):
                summary = "Fuel margin is critical for race completion."
                recommendation = "Lift and coast aggressively and reduce deployment on straights."
            elif any("Rain risk" in r for r in risks):
                summary = "Weather trend shows meaningful rain risk."
                recommendation = "Prepare for intermediates and protect tire temperatures."
            elif any("Overtake chance" in r for r in risks):
                summary = "You are within attack range of the car ahead."
                recommendation = "Use overtake mode on next straight and commit to a clean pass."
            else:
                summary = "No major strategic risk detected."
                recommendation = "Maintain pace and continue current stint plan."

        criticality = 2
        txt = f"{summary} {recommendation}".lower()
        if any(k in txt for k in ["box this lap", "critical", "fuel margin is critical"]):
            criticality = 5
        elif any(k in txt for k in ["prepare", "rain", "elevated", "low"]):
            criticality = 3

        return {
            **state,
            "summary": summary,
            "recommendation": recommendation,
            "criticality": criticality,
        }

    return _recommend_action_node



