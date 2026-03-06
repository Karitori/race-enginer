from datetime import datetime
from typing import Any

from db.contracts import TelemetryRepository
from utils.collections import first_or_none


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _timestamp_literal(value: Any) -> str:
    if isinstance(value, datetime):
        text = value.strftime("%Y-%m-%d %H:%M:%S.%f")
    else:
        text = str(value).strip().replace("T", " ")
    escaped = text.replace("'", "''")
    return f"TIMESTAMP '{escaped}'"


def _active_scope(repository: TelemetryRepository) -> dict[str, Any] | None:
    run_row = first_or_none(
        repository.query(
            """
            SELECT run_id, started_at
            FROM app_runs
            ORDER BY started_at DESC
            LIMIT 1
            """
        )
    )
    if not run_row:
        return None

    run_id = str(run_row[0])
    run_started_at = run_row[1]
    run_started_literal = _timestamp_literal(run_started_at)
    latest_session_row = first_or_none(
        repository.query(
            f"""
            SELECT timestamp, session_uid, session_type, track_id, total_laps
            FROM session_data
            WHERE timestamp >= {run_started_literal}
            ORDER BY timestamp DESC
            LIMIT 1
            """
        )
    )
    if not latest_session_row or latest_session_row[1] is None:
        return {
            "run_id": run_id,
            "run_started_at": str(run_started_at),
            "run_started_literal": run_started_literal,
            "session_uid": None,
        }

    latest_ts = latest_session_row[0]
    session_uid = _to_int(latest_session_row[1], default=0)
    session_type = _to_int(latest_session_row[2], default=0)
    track_id = _to_int(latest_session_row[3], default=-1)
    total_laps = _to_int(latest_session_row[4], default=0)

    session_start_row = first_or_none(
        repository.query(
            f"""
            SELECT MIN(timestamp)
            FROM session_data
            WHERE timestamp >= {run_started_literal}
              AND session_uid = {session_uid}
              AND session_type = {session_type}
              AND track_id = {track_id}
              AND total_laps = {total_laps}
            """
        )
    )
    session_started_at = session_start_row[0] if session_start_row and session_start_row[0] is not None else latest_ts
    session_started_literal = _timestamp_literal(session_started_at)

    return {
        "run_id": run_id,
        "run_started_at": str(run_started_at),
        "run_started_literal": run_started_literal,
        "session_uid": session_uid,
        "session_type": session_type,
        "track_id": track_id,
        "total_laps": total_laps,
        "session_started_at": str(session_started_at),
        "session_started_literal": session_started_literal,
        "latest_session_tick": str(latest_ts),
    }


def collect_strategy_snapshot(repository: TelemetryRepository) -> dict[str, Any]:
    """Collect a race-engineering snapshot with trends for strategy decisions."""
    scope = _active_scope(repository)
    if scope is None:
        return {"ready": False, "reason": "missing_app_run"}
    if scope.get("session_uid") is None:
        return {"ready": False, "reason": "waiting_for_live_packets", "scope": scope}

    session_uid = int(scope["session_uid"])
    session_started_literal = str(scope["session_started_literal"])
    scope_filter = f"session_uid = {session_uid} AND timestamp >= {session_started_literal}"

    wear_rows = repository.query(
        f"""
        SELECT tyres_wear_fl, tyres_wear_fr, tyres_wear_rl, tyres_wear_rr
        FROM car_damage
        WHERE {scope_filter} AND car_index = 0
        ORDER BY timestamp DESC LIMIT 20
        """
    )
    status_rows = repository.query(
        f"""
        SELECT fuel_in_tank, fuel_remaining_laps, actual_tyre_compound, tyres_age_laps,
               ers_store_energy, ers_deploy_mode, fuel_mix
        FROM car_status
        WHERE {scope_filter} AND car_index = 0
        ORDER BY timestamp DESC LIMIT 20
        """
    )
    lap_rows = repository.query(
        f"""
        SELECT last_lap_time_in_ms, car_position, delta_to_car_in_front_in_ms,
               delta_to_race_leader_in_ms, current_lap_num, num_pit_stops
        FROM lap_data
        WHERE {scope_filter} AND car_index = 0
        ORDER BY timestamp DESC LIMIT 20
        """
    )
    session_rows = repository.query(
        f"""
        SELECT weather, track_temperature, air_temperature, rain_percentage,
               pit_stop_window_ideal_lap, pit_stop_window_latest_lap,
               safety_car_status, total_laps, track_id
        FROM session_data
        WHERE {scope_filter}
        ORDER BY timestamp DESC LIMIT 5
        """
    )
    event_rows = repository.query(
        f"""
        SELECT event_code FROM race_events
        WHERE {scope_filter}
        ORDER BY timestamp DESC LIMIT 25
        """
    )
    packet_rows = repository.query(
        f"""
        SELECT packet_id, packet_name
        FROM raw_packets
        WHERE {scope_filter}
        ORDER BY timestamp DESC LIMIT 400
        """
    )

    latest_wear = first_or_none(wear_rows)
    latest_status = first_or_none(status_rows)
    latest_lap = first_or_none(lap_rows)
    latest_session = first_or_none(session_rows)

    wear_history_max = [
        max(_to_float(r[0]), _to_float(r[1]), _to_float(r[2]), _to_float(r[3]))
        for r in wear_rows
    ]
    wear_rate = 0.0
    if len(wear_history_max) >= 2:
        oldest = wear_history_max[-1]
        newest = wear_history_max[0]
        wear_rate = max(0.0, (newest - oldest) / (len(wear_history_max) - 1))

    fuel_history = [_to_float(r[0]) for r in status_rows]
    fuel_burn_per_sample = 0.0
    if len(fuel_history) >= 2:
        oldest_fuel = fuel_history[-1]
        newest_fuel = fuel_history[0]
        fuel_burn_per_sample = max(0.0, (oldest_fuel - newest_fuel) / (len(fuel_history) - 1))

    recent_laps = [_to_int(r[0]) for r in lap_rows if _to_int(r[0]) > 0]
    recent_avg_ms = _avg([float(v) for v in recent_laps[:3]])
    previous_avg_ms = _avg([float(v) for v in recent_laps[3:6]])
    pace_delta_ms = None
    if recent_avg_ms is not None and previous_avg_ms is not None:
        pace_delta_ms = recent_avg_ms - previous_avg_ms

    rain_values = [_to_int(r[3]) for r in session_rows]
    rain_trend = 0
    if len(rain_values) >= 2:
        rain_trend = rain_values[0] - rain_values[-1]

    event_codes = [_to_int(r[0], default=-1) if isinstance(r[0], int) else str(r[0]) for r in event_rows]
    recent_event_codes = [str(code) for code in event_codes if str(code)]
    safety_car_recent = any(code == "SAFC" for code in recent_event_codes)
    packet_ids_seen: list[int] = []
    packet_names_seen: list[str] = []
    for packet_row in packet_rows:
        packet_id = _to_int(packet_row[0], default=-1)
        packet_name = str(packet_row[1] or "")
        if packet_id >= 0 and packet_id not in packet_ids_seen:
            packet_ids_seen.append(packet_id)
        if packet_name and packet_name not in packet_names_seen:
            packet_names_seen.append(packet_name)

    if not latest_wear or not latest_status or not latest_lap or not latest_session:
        return {"ready": False, "reason": "incomplete_session_rows", "scope": scope}

    fuel_remaining_laps = _to_float(latest_status[1])
    current_lap = _to_int(latest_lap[4], default=1)
    total_laps = _to_int(latest_session[7], default=0)
    laps_remaining = max(0, total_laps - current_lap) if total_laps > 0 else 0
    pit_window_ideal = _to_int(latest_session[4], default=0)
    pit_window_latest = _to_int(latest_session[5], default=0)
    in_pit_window = (
        pit_window_ideal > 0
        and pit_window_latest >= pit_window_ideal
        and pit_window_ideal <= current_lap <= pit_window_latest
    )

    wear_fl = _to_float(latest_wear[0])
    wear_fr = _to_float(latest_wear[1])
    wear_rl = _to_float(latest_wear[2])
    wear_rr = _to_float(latest_wear[3])

    front_avg_wear = (wear_fl + wear_fr) / 2.0
    rear_avg_wear = (wear_rl + wear_rr) / 2.0
    max_wear = max(wear_fl, wear_fr, wear_rl, wear_rr)

    ers_pct = max(0.0, min(100.0, _to_float(latest_status[4]) / 4_000_000.0 * 100.0))

    compound_codes_seen = []
    for row in status_rows:
        code = _to_int(row[2], default=-1)
        if code > 0 and code not in compound_codes_seen:
            compound_codes_seen.append(code)
    wet_codes = {7, 8}
    dry_compounds_used = [code for code in compound_codes_seen if code not in wet_codes]
    wet_or_intermediate_used = any(code in wet_codes for code in compound_codes_seen)
    sets_used_estimate = max(1, _to_int(latest_lap[5], default=0) + 1)
    track_id = _to_int(latest_session[8], default=-1)

    return {
        "ready": True,
        "scope": scope,
        "stint": {
            "compound_code": _to_int(latest_status[2]),
            "tyre_age_laps": _to_int(latest_status[3]),
            "wear_fl_pct": wear_fl,
            "wear_fr_pct": wear_fr,
            "wear_rl_pct": wear_rl,
            "wear_rr_pct": wear_rr,
            "wear_front_avg_pct": front_avg_wear,
            "wear_rear_avg_pct": rear_avg_wear,
            "wear_max_pct": max_wear,
            "wear_rate_pct_per_sample": wear_rate,
            "compound_codes_seen": compound_codes_seen,
            "dry_compounds_used_count": len(dry_compounds_used),
            "wet_or_intermediate_used": wet_or_intermediate_used,
        },
        "energy": {
            "fuel_kg": _to_float(latest_status[0]),
            "fuel_laps_remaining": fuel_remaining_laps,
            "fuel_mix_code": _to_int(latest_status[6]),
            "fuel_burn_kg_per_sample": fuel_burn_per_sample,
            "ers_pct": ers_pct,
            "ers_mode_code": _to_int(latest_status[5]),
        },
        "race": {
            "position": _to_int(latest_lap[1]),
            "gap_front_ms": _to_int(latest_lap[2]),
            "gap_leader_ms": _to_int(latest_lap[3]),
            "current_lap": current_lap,
            "total_laps": total_laps,
            "laps_remaining": laps_remaining,
            "pit_stops": _to_int(latest_lap[5]),
            "sets_used_estimate": sets_used_estimate,
        },
        "pace": {
            "recent_avg_lap_ms": recent_avg_ms,
            "previous_avg_lap_ms": previous_avg_ms,
            "pace_delta_ms": pace_delta_ms,
        },
        "conditions": {
            "weather_code": _to_int(latest_session[0]),
            "track_temp_c": _to_int(latest_session[1]),
            "air_temp_c": _to_int(latest_session[2]),
            "rain_pct": _to_int(latest_session[3]),
            "rain_trend_pct": rain_trend,
            "pit_window_ideal_lap": pit_window_ideal,
            "pit_window_latest_lap": pit_window_latest,
            "in_pit_window": in_pit_window,
            "safety_car_status": _to_int(latest_session[6]),
            "track_id": track_id,
            "is_monaco": track_id == 5,
        },
        "signals": {
            "recent_event_codes": recent_event_codes,
            "safety_car_recent": safety_car_recent,
        },
        "telemetry_coverage": {
            "packet_ids_seen_recently": packet_ids_seen,
            "packet_names_seen_recently": packet_names_seen,
            "full_surface_active": all(packet_id in packet_ids_seen for packet_id in range(16)),
        },
    }



