import pytest

from nodes.strategy_analysis_nodes import make_regulations_node, make_strategy_wall_node


@pytest.mark.asyncio
async def test_regulations_node_flags_dry_compound_obligation():
    node = make_regulations_node()
    state = {
        "snapshot": {
            "ready": True,
            "stint": {
                "dry_compounds_used_count": 1,
                "wet_or_intermediate_used": False,
            },
            "race": {
                "current_lap": 35,
                "total_laps": 58,
                "laps_remaining": 23,
                "sets_used_estimate": 1,
            },
            "conditions": {
                "rain_pct": 5,
                "is_monaco": False,
            },
        },
        "team_calls": [],
    }

    result = await node(state)
    calls = result["team_calls"]
    assert calls
    assert calls[-1]["desk"] == "regulations"
    assert "dry_compound_requirement" in calls[-1]["risk_tags"]
    assert calls[-1]["priority"] >= 3


@pytest.mark.asyncio
async def test_regulations_node_flags_monaco_stop_obligation():
    node = make_regulations_node()
    state = {
        "snapshot": {
            "ready": True,
            "stint": {
                "dry_compounds_used_count": 1,
                "wet_or_intermediate_used": False,
            },
            "race": {
                "current_lap": 42,
                "total_laps": 78,
                "laps_remaining": 36,
                "sets_used_estimate": 1,
            },
            "conditions": {
                "rain_pct": 0,
                "is_monaco": True,
            },
        },
        "team_calls": [],
    }

    result = await node(state)
    call = result["team_calls"][-1]
    assert call["desk"] == "regulations"
    assert "monaco_two_stop_requirement" in call["risk_tags"]
    assert call["priority"] >= 3


@pytest.mark.asyncio
async def test_strategy_wall_node_identifies_undercut_window():
    node = make_strategy_wall_node()
    state = {
        "snapshot": {
            "race": {
                "gap_front_ms": 1400,
                "laps_remaining": 18,
            },
            "pace": {
                "pace_delta_ms": 310.0,
            },
            "stint": {
                "wear_max_pct": 69.0,
                "wear_rate_pct_per_sample": 0.42,
            },
            "energy": {
                "ers_pct": 45.0,
                "fuel_laps_remaining": 19.0,
            },
            "conditions": {
                "in_pit_window": True,
                "safety_car_status": 0,
            },
        },
        "team_calls": [],
    }

    result = await node(state)
    call = result["team_calls"][-1]
    assert call["desk"] == "strategy_wall"
    assert "undercut_window" in call["risk_tags"]
    assert "Box this lap" in call["action"]


@pytest.mark.asyncio
async def test_strategy_wall_prioritizes_track_position_on_hard_track():
    node = make_strategy_wall_node()
    state = {
        "snapshot": {
            "race": {
                "gap_front_ms": 1200,
                "laps_remaining": 30,
            },
            "pace": {
                "pace_delta_ms": 50.0,
            },
            "stint": {
                "wear_max_pct": 64.0,
                "wear_rate_pct_per_sample": 0.1,
            },
            "energy": {
                "ers_pct": 40.0,
                "fuel_laps_remaining": 31.0,
            },
            "conditions": {
                "in_pit_window": True,
                "safety_car_status": 0,
                "track_id": 5,
            },
        },
        "team_calls": [],
    }

    result = await node(state)
    call = result["team_calls"][-1]
    assert call["desk"] == "strategy_wall"
    assert "track_position_priority" in call["risk_tags"]
    assert "track position" in call["action"].lower()


@pytest.mark.asyncio
async def test_racecraft_prefers_pressure_on_hard_overtake_track():
    from nodes.strategy_analysis_nodes import make_racecraft_node

    node = make_racecraft_node()
    state = {
        "snapshot": {
            "race": {
                "gap_front_ms": 900,
                "laps_remaining": 15,
            },
            "pace": {
                "pace_delta_ms": 0.0,
            },
            "energy": {
                "ers_pct": 50.0,
                "fuel_laps_remaining": 16.0,
            },
            "conditions": {
                "safety_car_status": 0,
                "track_id": 5,
            },
            "signals": {
                "safety_car_recent": False,
            },
        },
        "team_calls": [],
    }

    result = await node(state)
    call = result["team_calls"][-1]
    assert call["desk"] == "racecraft"
    assert "track_position_priority" in call["risk_tags"]
    assert "drs" in call["action"].lower()
