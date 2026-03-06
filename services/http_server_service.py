import logging

import uvicorn
from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def start_http_server(
    app: FastAPI, host: str = "0.0.0.0", port: int = 8000, log_level: str = "info"
):
    """Run the FastAPI server for dashboard and API routes."""
    config = uvicorn.Config(app, host=host, port=port, log_level=log_level)
    server = uvicorn.Server(config)
    logger.info("Starting UI server on http://localhost:%s", port)
    await server.serve()

