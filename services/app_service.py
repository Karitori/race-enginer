from fastapi import FastAPI

from routes.api_routes import router as api_router
from routes.dashboard_routes import router as dashboard_router
from routes.route_context import set_datastore, set_parser_manager, set_voice_assistant
from routes.websocket_routes import router as ws_router

app = FastAPI(title="Race Engineer Dashboard")
app.include_router(api_router)
app.include_router(dashboard_router)
app.include_router(ws_router)

__all__ = ["app", "set_datastore", "set_parser_manager", "set_voice_assistant"]
