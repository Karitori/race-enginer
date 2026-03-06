import asyncio
from typing import Any, Awaitable, Callable, TypedDict

from db.contracts import TelemetryRepository
from tools.strategy_snapshot_tool import build_strategy_snapshot_tool
from utils.f1_25_strategy_knowledge import (
    AGGRESSIVE_OVERTAKE_GAP_MS,
    CRITICAL_TIRE_WEAR_PCT,
    DEGRADATION_RISING_PCT_PER_SAMPLE,
    ERS_ATTACK_PCT,
    ERS_LOW_PCT,
    FUEL_CRITICAL_BUFFER_LAPS,
    FUEL_LOW_BUFFER_LAPS,
    HIGH_TIRE_WEAR_PCT,
    OVERTAKE_GAP_MS,
    PACE_DROP_ALERT_MS,
    RAIN_ALERT_PCT,
    RAIN_HEAVY_PCT,
    RAIN_TO_INTERMEDIATE_PCT,
    RAIN_TO_WET_PCT,
    RAIN_TREND_ALERT_DELTA,
    SAFETY_CAR_PIT_WEAR_THRESHOLD_PCT,
    compound_name,
    recommend_next_compound,
)


class TeamCall(TypedDict, total=False):
    desk: str
    priority: int
    title: str
    action: str
    rationale: str
    confidence: float
    risk_tags: list[str]


class StrategyState(TypedDict, total=False):
    snapshot: dict[str, Any]
    team_calls: list[TeamCall]
    risks: list[str]
    summary: str
    recommendation: str
    criticality: int
    confidence: float
    risk_tags: list[str]
    pit_call: str | None
    fuel_call: str | None
    ers_call: str | None
    team_notes: list[str]


LLMRunner = Callable[
    [dict[str, Any], list[TeamCall], dict[str, Any]],
    Awaitable[dict[str, Any] | None],
]


def _clamp_int(value: Any, low: int, high: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, parsed))


def _clamp_float(value: Any, low: float, high: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, parsed))


def _append_call(state: StrategyState, call: TeamCall) -> StrategyState:
    calls = list(state.get("team_calls", []))
    calls.append(call)
    return {**state, "team_calls": calls}


def make_collect_metrics_node(repository: TelemetryRepository):
    snapshot_tool = build_strategy_snapshot_tool(repository)

    async def _collect_metrics_node(state: StrategyState) -> StrategyState:
        loop = asyncio.get_running_loop()
        snapshot = await loop.run_in_executor(None, lambda: snapshot_tool.invoke({}))
        if not isinstance(snapshot, dict):
            snapshot = {"ready": False}
        return {**state, "snapshot": snapshot, "team_calls": []}

    return _collect_metrics_node


def make_tire_wall_node():
    async def _tire_wall_node(state: StrategyState) -> StrategyState:
        snapshot = state.get("snapshot", {})
        if not snapshot.get("ready"):
            return _append_call(
                state,
                {
                    "desk": "tire_wall",
                    "priority": 1,
                    "title": "Waiting for stable stint data",
                    "action": "Hold current tire plan until complete telemetry arrives.",
                    "rationale": "Stint metrics are incomplete.",
                    "confidence": 0.3,
                    "risk_tags": ["telemetry_unavailable"],
                },
            )

        stint = snapshot.get("stint", {})
        conditions = snapshot.get("conditions", {})
        race = snapshot.get("race", {})

        wear_max = float(stint.get("wear_max_pct", 0.0))
        wear_rate = float(stint.get("wear_rate_pct_per_sample", 0.0))
        tyre_age = int(stint.get("tyre_age_laps", 0))
        current_compound = int(stint.get("compound_code", 17))
        rain_pct = int(conditions.get("rain_pct", 0))
        in_pit_window = bool(conditions.get("in_pit_window", False))
        laps_remaining = int(race.get("laps_remaining", 0))

        next_compound_code = recommend_next_compound(
            current_compound=current_compound,
            rain_pct=rain_pct,
            laps_remaining=laps_remaining,
        )
        next_compound = compound_name(next_compound_code)

        if wear_max >= CRITICAL_TIRE_WEAR_PCT:
            return _append_call(
                state,
                {
                    "desk": "tire_wall",
                    "priority": 5,
                    "title": "Critical tire degradation",
                    "action": f"Box this lap for {next_compound}.",
                    "rationale": f"Peak tire wear is {wear_max:.1f}%, beyond safe operating range.",
                    "confidence": 0.92,
                    "risk_tags": ["tire_critical", "pit_now"],
                },
            )

        if wear_max >= HIGH_TIRE_WEAR_PCT and in_pit_window:
            return _append_call(
                state,
                {
                    "desk": "tire_wall",
                    "priority": 4,
                    "title": "High wear inside pit window",
                    "action": f"Pit this lap or next lap for {next_compound}.",
                    "rationale": f"Max wear {wear_max:.1f}% with window open.",
                    "confidence": 0.84,
                    "risk_tags": ["tire_high", "pit_window_open"],
                },
            )

        if rain_pct >= RAIN_ALERT_PCT and current_compound in (16, 17, 18):
            rain_compound = (
                "Intermediates" if rain_pct < RAIN_TO_WET_PCT else "Wets"
            )
            return _append_call(
                state,
                {
                    "desk": "tire_wall",
                    "priority": 4,
                    "title": "Cross-over tire condition",
                    "action": f"Prepare switch to {rain_compound} on next stop.",
                    "rationale": f"Rain probability is {rain_pct}% on dry compound.",
                    "confidence": 0.8,
                    "risk_tags": ["weather_crossover", "pit_plan"],
                },
            )

        if (
            tyre_age >= 20
            and wear_rate >= DEGRADATION_RISING_PCT_PER_SAMPLE
            and in_pit_window
        ):
            return _append_call(
                state,
                {
                    "desk": "tire_wall",
                    "priority": 3,
                    "title": "Stint fading",
                    "action": "Prefer undercut option within next two laps.",
                    "rationale": (
                        f"Tire age {tyre_age} laps, wear growth {wear_rate:.2f}%/sample."
                    ),
                    "confidence": 0.72,
                    "risk_tags": ["degradation_rising"],
                },
            )

        return _append_call(
            state,
            {
                "desk": "tire_wall",
                "priority": 1,
                "title": "Stint stable",
                "action": "Continue current compound and monitor degradation trend.",
                "rationale": f"Max wear {wear_max:.1f}% remains manageable.",
                "confidence": 0.68,
                "risk_tags": [],
            },
        )

    return _tire_wall_node


def make_energy_wall_node():
    async def _energy_wall_node(state: StrategyState) -> StrategyState:
        snapshot = state.get("snapshot", {})
        energy = snapshot.get("energy", {})
        race = snapshot.get("race", {})

        fuel_laps = float(energy.get("fuel_laps_remaining", 0.0))
        laps_remaining = int(race.get("laps_remaining", 0))
        ers_pct = float(energy.get("ers_pct", 0.0))
        gap_front_ms = int(race.get("gap_front_ms", 99999))

        if laps_remaining > 0 and fuel_laps + FUEL_CRITICAL_BUFFER_LAPS < laps_remaining:
            state = _append_call(
                state,
                {
                    "desk": "energy_wall",
                    "priority": 5,
                    "title": "Fuel critical to finish",
                    "action": "Immediate lift-and-coast and short-shift fuel save mode.",
                    "rationale": (
                        f"Fuel projection {fuel_laps:.1f} laps vs {laps_remaining} laps remaining."
                    ),
                    "confidence": 0.9,
                    "risk_tags": ["fuel_critical"],
                },
            )
        elif laps_remaining > 0 and fuel_laps + FUEL_LOW_BUFFER_LAPS < laps_remaining:
            state = _append_call(
                state,
                {
                    "desk": "energy_wall",
                    "priority": 4,
                    "title": "Fuel margin low",
                    "action": "Use medium fuel saving in sectors one and three.",
                    "rationale": (
                        f"Fuel projection {fuel_laps:.1f} laps vs {laps_remaining} remaining."
                    ),
                    "confidence": 0.8,
                    "risk_tags": ["fuel_low"],
                },
            )

        if ers_pct <= ERS_LOW_PCT:
            return _append_call(
                state,
                {
                    "desk": "energy_wall",
                    "priority": 3,
                    "title": "ERS reserve low",
                    "action": "Prioritize harvest for two sectors before next attack.",
                    "rationale": f"ERS store is only {ers_pct:.0f}%.",
                    "confidence": 0.78,
                    "risk_tags": ["ers_low"],
                },
            )

        if ers_pct >= ERS_ATTACK_PCT and 0 < gap_front_ms <= OVERTAKE_GAP_MS:
            return _append_call(
                state,
                {
                    "desk": "energy_wall",
                    "priority": 3,
                    "title": "ERS attack window",
                    "action": "Deploy overtake mode on the next straight.",
                    "rationale": (
                        f"ERS {ers_pct:.0f}% with front gap {gap_front_ms/1000:.3f}s."
                    ),
                    "confidence": 0.75,
                    "risk_tags": ["ers_attack_window"],
                },
            )

        return _append_call(
            state,
            {
                "desk": "energy_wall",
                "priority": 1,
                "title": "Energy balance acceptable",
                "action": "Maintain balanced deploy and harvest profile.",
                "rationale": "Fuel and ERS margins are inside acceptable bounds.",
                "confidence": 0.65,
                "risk_tags": [],
            },
        )

    return _energy_wall_node


def make_race_control_node():
    async def _race_control_node(state: StrategyState) -> StrategyState:
        snapshot = state.get("snapshot", {})
        stint = snapshot.get("stint", {})
        conditions = snapshot.get("conditions", {})
        signals = snapshot.get("signals", {})

        safety_car_status = int(conditions.get("safety_car_status", 0))
        safety_car_recent = bool(signals.get("safety_car_recent", False))
        in_pit_window = bool(conditions.get("in_pit_window", False))
        rain_pct = int(conditions.get("rain_pct", 0))
        rain_trend = int(conditions.get("rain_trend_pct", 0))
        wear_max = float(stint.get("wear_max_pct", 0.0))

        if safety_car_status > 0 or safety_car_recent:
            if in_pit_window and wear_max >= SAFETY_CAR_PIT_WEAR_THRESHOLD_PCT:
                return _append_call(
                    state,
                    {
                        "desk": "race_control",
                        "priority": 5,
                        "title": "Safety car pit opportunity",
                        "action": "Box under safety car to secure track-position gain.",
                        "rationale": "Reduced pit-loss window plus moderate tire wear.",
                        "confidence": 0.88,
                        "risk_tags": ["safety_car", "pit_opportunity"],
                    },
                )
            return _append_call(
                state,
                {
                    "desk": "race_control",
                    "priority": 4,
                    "title": "Neutralized race conditions",
                    "action": "Manage delta and protect tire temperatures for restart.",
                    "rationale": "Safety car conditions active or recently triggered.",
                    "confidence": 0.82,
                    "risk_tags": ["safety_car"],
                },
            )

        if rain_pct >= RAIN_HEAVY_PCT:
            return _append_call(
                state,
                {
                    "desk": "race_control",
                    "priority": 5,
                    "title": "Heavy rain threat",
                    "action": "Prepare immediate wet-weather stop if grip drops.",
                    "rationale": f"Rain probability at {rain_pct}%.",
                    "confidence": 0.9,
                    "risk_tags": ["rain_heavy"],
                },
            )

        if rain_pct >= RAIN_TO_INTERMEDIATE_PCT or rain_trend >= RAIN_TREND_ALERT_DELTA:
            return _append_call(
                state,
                {
                    "desk": "race_control",
                    "priority": 4,
                    "title": "Rain trend increasing",
                    "action": "Pre-arm intermediate strategy and protect tire surface temps.",
                    "rationale": f"Rain {rain_pct}% with trend change {rain_trend:+d}.",
                    "confidence": 0.8,
                    "risk_tags": ["rain_rising"],
                },
            )

        return _append_call(
            state,
            {
                "desk": "race_control",
                "priority": 1,
                "title": "Conditions stable",
                "action": "Proceed with primary race plan.",
                "rationale": "No active weather or race-control disruptions.",
                "confidence": 0.66,
                "risk_tags": [],
            },
        )

    return _race_control_node


def make_racecraft_node():
    async def _racecraft_node(state: StrategyState) -> StrategyState:
        snapshot = state.get("snapshot", {})
        race = snapshot.get("race", {})
        pace = snapshot.get("pace", {})
        energy = snapshot.get("energy", {})

        gap_front_ms = int(race.get("gap_front_ms", 99999))
        pace_delta_ms = pace.get("pace_delta_ms")
        ers_pct = float(energy.get("ers_pct", 0.0))
        fuel_laps = float(energy.get("fuel_laps_remaining", 0.0))
        laps_remaining = int(race.get("laps_remaining", 0))

        if (
            0 < gap_front_ms <= AGGRESSIVE_OVERTAKE_GAP_MS
            and ers_pct >= 25
            and fuel_laps >= laps_remaining
        ):
            return _append_call(
                state,
                {
                    "desk": "racecraft",
                    "priority": 3,
                    "title": "Overtake opportunity",
                    "action": "Use DRS/ERS combo to attempt pass on next straight.",
                    "rationale": f"Front gap {gap_front_ms/1000:.3f}s with usable ERS.",
                    "confidence": 0.78,
                    "risk_tags": ["overtake_window"],
                },
            )

        if isinstance(pace_delta_ms, (int, float)) and pace_delta_ms > PACE_DROP_ALERT_MS:
            return _append_call(
                state,
                {
                    "desk": "racecraft",
                    "priority": 2,
                    "title": "Pace drop detected",
                    "action": "Protect rear tires and reset braking references.",
                    "rationale": f"Pace is slower by {pace_delta_ms:.0f}ms vs previous phase.",
                    "confidence": 0.7,
                    "risk_tags": ["pace_drop"],
                },
            )

        return _append_call(
            state,
            {
                "desk": "racecraft",
                "priority": 1,
                "title": "Racecraft stable",
                "action": "Maintain pressure and avoid unnecessary risk.",
                "rationale": "No immediate attack/defend trigger above threshold.",
                "confidence": 0.64,
                "risk_tags": [],
            },
        )

    return _racecraft_node


def _extract_call(calls: list[TeamCall], keyword: str) -> str | None:
    for call in calls:
        action = str(call.get("action", "")).lower()
        tags = [str(t).lower() for t in call.get("risk_tags", [])]
        if keyword in action or any(keyword in t for t in tags):
            return str(call.get("action", ""))
    return None


def _deterministic_decision(calls: list[TeamCall]) -> dict[str, Any]:
    sorted_calls = sorted(calls, key=lambda c: int(c.get("priority", 1)), reverse=True)
    if not sorted_calls:
        return {
            "summary": "No paddock calls generated.",
            "recommendation": "Hold plan until telemetry updates.",
            "criticality": 1,
            "confidence": 0.3,
            "risk_tags": [],
            "pit_call": None,
            "fuel_call": None,
            "ers_call": None,
            "team_notes": [],
        }

    primary = sorted_calls[0]
    secondary = sorted_calls[1] if len(sorted_calls) > 1 else None

    risk_tags: list[str] = []
    for call in sorted_calls:
        for tag in call.get("risk_tags", []):
            tag_text = str(tag)
            if tag_text and tag_text not in risk_tags:
                risk_tags.append(tag_text)

    summary = str(primary.get("title", "Strategy update"))
    if secondary and int(secondary.get("priority", 1)) >= 3:
        summary = f"{summary}; {secondary.get('title', 'secondary condition active')}"

    recommendation = str(primary.get("action", "Maintain current plan."))
    if secondary and int(secondary.get("priority", 1)) >= 4:
        recommendation = f"{recommendation} Then {secondary.get('action', '').lower()}"

    top_calls = sorted_calls[:3]
    confidence_values = [float(c.get("confidence", 0.5)) for c in top_calls]
    confidence = sum(confidence_values) / len(confidence_values)

    return {
        "summary": summary,
        "recommendation": recommendation,
        "criticality": max(1, min(5, int(primary.get("priority", 1)))),
        "confidence": max(0.0, min(1.0, confidence)),
        "risk_tags": risk_tags,
        "pit_call": _extract_call(sorted_calls, "pit"),
        "fuel_call": _extract_call(sorted_calls, "fuel"),
        "ers_call": _extract_call(sorted_calls, "ers"),
        "team_notes": [
            f"{call.get('desk', 'desk')}: {call.get('rationale', '')}"
            for call in sorted_calls[:4]
        ],
    }


def make_synthesize_decision_node(llm_runner: LLMRunner | None = None):
    async def _synthesize_decision_node(state: StrategyState) -> StrategyState:
        snapshot = state.get("snapshot", {})
        calls = list(state.get("team_calls", []))
        decision = _deterministic_decision(calls)

        if llm_runner:
            llm_payload = await llm_runner(snapshot, calls, decision)
            if isinstance(llm_payload, dict):
                decision["summary"] = str(llm_payload.get("summary", decision["summary"]))
                decision["recommendation"] = str(
                    llm_payload.get("recommendation", decision["recommendation"])
                )
                decision["criticality"] = _clamp_int(
                    llm_payload.get("criticality"),
                    low=1,
                    high=5,
                    fallback=int(decision["criticality"]),
                )
                decision["confidence"] = _clamp_float(
                    llm_payload.get("confidence"),
                    low=0.0,
                    high=1.0,
                    fallback=float(decision["confidence"]),
                )
                llm_risks = llm_payload.get("risk_tags")
                if isinstance(llm_risks, list):
                    decision["risk_tags"] = [str(tag) for tag in llm_risks if str(tag)]
                for key in ("pit_call", "fuel_call", "ers_call"):
                    if key in llm_payload:
                        value = llm_payload.get(key)
                        decision[key] = None if value is None else str(value)
                llm_notes = llm_payload.get("team_notes")
                if isinstance(llm_notes, list):
                    decision["team_notes"] = [str(note) for note in llm_notes if str(note)]

        return {
            **state,
            "risks": list(decision["risk_tags"]),
            "summary": str(decision["summary"]),
            "recommendation": str(decision["recommendation"]),
            "criticality": int(decision["criticality"]),
            "confidence": float(decision["confidence"]),
            "risk_tags": list(decision["risk_tags"]),
            "pit_call": decision["pit_call"],
            "fuel_call": decision["fuel_call"],
            "ers_call": decision["ers_call"],
            "team_notes": list(decision["team_notes"]),
        }

    return _synthesize_decision_node
