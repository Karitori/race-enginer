from fastapi import APIRouter

from models.api import DriverQueryPayload, SQLQueryPayload, TelemetryModePayload
from models.telemetry import DriverQuery, TalkLevelPayload
from routes.route_context import get_datastore, get_parser_manager
from services.event_bus_service import bus

router = APIRouter()


@router.post("/api/driver_query")
async def receive_manual_driver_query(payload: DriverQueryPayload):
    """Endpoint to simulate the driver speaking via a UI button."""
    query = DriverQuery(query=payload.query, confidence=1.0)
    await bus.publish("driver_query", query)
    return {"status": "success"}


@router.post("/api/talk_level")
async def receive_talk_level(payload: TalkLevelPayload):
    """Endpoint to set the verbosity level of the Race Engineer."""
    await bus.publish("talk_level_changed", {"talk_level": payload.talk_level})
    return {"status": "success", "talk_level": payload.talk_level}


@router.get("/api/telemetry_status")
async def get_telemetry_status():
    """Get current telemetry mode and connection status."""
    parser_manager = get_parser_manager()
    if parser_manager is None:
        return {"mode": "real", "status": "not_started"}
    return parser_manager.get_status()


@router.post("/api/telemetry_mode")
async def set_telemetry_mode(payload: TelemetryModePayload):
    """Switch between mock and real telemetry modes."""
    parser_manager = get_parser_manager()
    if parser_manager is None:
        return {"status": "error", "error": "Parser manager not initialized"}
    if payload.mode not in ("mock", "real"):
        return {"status": "error", "error": "Mode must be 'mock' or 'real'"}
    await parser_manager.switch_mode(payload.mode, payload.host, payload.port)
    return {"status": "success", "mode": payload.mode}


@router.post("/api/query")
async def execute_sql_query(payload: SQLQueryPayload):
    """Endpoint for SQL reads via the main process to avoid lock contention."""
    datastore = get_datastore()
    if datastore is None:
        return {"status": "error", "error": "Telemetry repository not initialized yet"}
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        rows = await loop.run_in_executor(None, datastore.query, payload.sql)
        return {"status": "success", "rows": rows}
    except Exception as e:
        return {"status": "error", "error": str(e)}
