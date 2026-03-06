import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from routes.route_context import get_voice_assistant
from services.event_bus_service import bus

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    queue: asyncio.Queue = asyncio.Queue()

    async def telemetry_handler(data):
        await queue.put({"topic": "telemetry_tick", "payload": data.model_dump()})

    async def insight_handler(data):
        await queue.put({"topic": "driving_insight", "payload": data.model_dump()})

    async def car_telemetry_handler(data):
        idx = data.header.player_car_index
        if idx >= len(data.car_telemetry_data):
            return
        ct = data.car_telemetry_data[idx]
        await queue.put(
            {
                "topic": "car_telemetry_ext",
                "payload": {
                    "surface_temps": ct.tyres_surface_temperature,
                    "inner_temps": ct.tyres_inner_temperature,
                    "brake_temps": ct.brakes_temperature,
                    "pressures": ct.tyres_pressure,
                    "drs": ct.drs,
                    "engine_temp": ct.engine_temperature,
                },
            }
        )

    async def car_status_handler(data):
        idx = data.header.player_car_index
        if idx >= len(data.car_status_data):
            return
        s = data.car_status_data[idx]
        await queue.put(
            {
                "topic": "car_status_ext",
                "payload": {
                    "ers_store": s.ers_store_energy,
                    "ers_mode": s.ers_deploy_mode,
                    "fuel_in_tank": s.fuel_in_tank,
                    "fuel_remaining_laps": s.fuel_remaining_laps,
                    "fuel_mix": s.fuel_mix,
                    "visual_compound": s.visual_tyre_compound,
                    "tyre_age": s.tyres_age_laps,
                    "drs_allowed": s.drs_allowed,
                },
            }
        )

    async def car_damage_handler(data):
        idx = data.header.player_car_index
        if idx >= len(data.car_damage_data):
            return
        d = data.car_damage_data[idx]
        await queue.put(
            {
                "topic": "car_damage_ext",
                "payload": {
                    "fl_wing": d.front_left_wing_damage,
                    "fr_wing": d.front_right_wing_damage,
                    "rear_wing": d.rear_wing_damage,
                    "floor": d.floor_damage,
                    "diffuser": d.diffuser_damage,
                    "sidepod": d.sidepod_damage,
                    "gearbox": d.gear_box_damage,
                    "engine": d.engine_damage,
                },
            }
        )

    async def session_handler(data):
        await queue.put(
            {
                "topic": "session_info",
                "payload": {
                    "weather": data.weather,
                    "track_temp": data.track_temperature,
                    "air_temp": data.air_temperature,
                    "time_left": data.session_time_left,
                    "safety_car": data.safety_car_status,
                    "pit_ideal": data.pit_stop_window_ideal_lap,
                    "pit_latest": data.pit_stop_window_latest_lap,
                },
            }
        )

    async def lap_data_handler(data):
        idx = data.header.player_car_index
        if idx >= len(data.car_lap_data):
            return
        lap = data.car_lap_data[idx]
        await queue.put(
            {
                "topic": "lap_info",
                "payload": {
                    "position": lap.car_position,
                    "total_cars": 20,
                    "gap_front": lap.delta_to_car_in_front_in_ms,
                    "gap_leader": lap.delta_to_race_leader_in_ms,
                    "last_lap": lap.last_lap_time_in_ms,
                    "pit_stops": lap.num_pit_stops,
                },
            }
        )

    async def event_handler(data):
        detail = ""
        d = data.event_details
        if d.speed is not None:
            detail = f" ({d.speed:.0f} km/h)"
        elif d.lap_time is not None:
            detail = f" ({d.lap_time:.3f}s)"
        elif d.overtaking_vehicle_idx is not None:
            detail = (
                f" (car {d.overtaking_vehicle_idx} overtakes "
                f"{d.being_overtaken_vehicle_idx})"
            )
        await queue.put(
            {
                "topic": "race_event",
                "payload": {
                    "code": data.event_string_code,
                    "text": f"[{data.event_string_code}]{detail}",
                },
            }
        )

    async def telemetry_status_handler(data):
        await queue.put({"topic": "telemetry_status", "payload": data})

    async def stt_status_handler(data):
        await queue.put({"topic": "stt_status", "payload": data})

    async def driver_transcript_handler(data):
        await queue.put({"topic": "driver_transcript", "payload": data})

    bus.subscribe("telemetry_tick", telemetry_handler)
    bus.subscribe("driving_insight", insight_handler)
    bus.subscribe("packet_car_telemetry", car_telemetry_handler)
    bus.subscribe("packet_car_status", car_status_handler)
    bus.subscribe("packet_car_damage", car_damage_handler)
    bus.subscribe("packet_session", session_handler)
    bus.subscribe("packet_lap_data", lap_data_handler)
    bus.subscribe("packet_event", event_handler)
    bus.subscribe("telemetry_status", telemetry_status_handler)
    bus.subscribe("stt_status", stt_status_handler)
    bus.subscribe("driver_transcript", driver_transcript_handler)

    voice_assistant = get_voice_assistant()
    if voice_assistant is not None:
        await queue.put(
            {
                "topic": "stt_status",
                "payload": voice_assistant.get_stt_status(),
            }
        )

    try:
        while True:
            msg = await queue.get()
            await websocket.send_json(msg)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("websocket error: %s", e)
    finally:
        bus.unsubscribe("telemetry_tick", telemetry_handler)
        bus.unsubscribe("driving_insight", insight_handler)
        bus.unsubscribe("packet_car_telemetry", car_telemetry_handler)
        bus.unsubscribe("packet_car_status", car_status_handler)
        bus.unsubscribe("packet_car_damage", car_damage_handler)
        bus.unsubscribe("packet_session", session_handler)
        bus.unsubscribe("packet_lap_data", lap_data_handler)
        bus.unsubscribe("packet_event", event_handler)
        bus.unsubscribe("telemetry_status", telemetry_status_handler)
        bus.unsubscribe("stt_status", stt_status_handler)
        bus.unsubscribe("driver_transcript", driver_transcript_handler)
