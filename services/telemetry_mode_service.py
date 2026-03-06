import asyncio
from typing import Any

from services.event_bus_service import bus
from services.mock_telemetry_service import BaseTelemetryParser


class TelemetryModeService:
    """Manage switching between mock and real telemetry runtime services."""

    def __init__(self):
        self.mode = "mock"
        self._mock_parser = BaseTelemetryParser()
        self._real_parser = None
        self._active_task: asyncio.Task[Any] | None = None
        self.host = "0.0.0.0"
        self.port = 20777

    async def start(self):
        self._active_task = asyncio.create_task(self._mock_parser.start())
        await bus.publish("telemetry_status", {"mode": "mock", "status": "running"})
        try:
            await self._active_task
        except asyncio.CancelledError:
            pass

    async def switch_mode(
        self, mode: str, host: str | None = None, port: int | None = None
    ):
        if mode == self.mode:
            return

        if self.mode == "mock":
            self._mock_parser.stop()
        elif self._real_parser:
            self._real_parser.stop()

        if self._active_task and not self._active_task.done():
            self._active_task.cancel()
            try:
                await self._active_task
            except asyncio.CancelledError:
                pass

        self.mode = mode
        if host is not None:
            self.host = host
        if port is not None:
            self.port = port

        if mode == "mock":
            self._mock_parser = BaseTelemetryParser()
            self._active_task = asyncio.create_task(self._mock_parser.start())
            await bus.publish("telemetry_status", {"mode": "mock", "status": "running"})
        else:
            from services.real_telemetry_service import RealTelemetryParser

            self._real_parser = RealTelemetryParser(host=self.host, port=self.port)
            self._active_task = asyncio.create_task(self._real_parser.start())

    def stop(self):
        if self.mode == "mock":
            self._mock_parser.stop()
        elif self._real_parser:
            self._real_parser.stop()
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()

    def get_status(self) -> dict[str, Any]:
        if self.mode == "mock":
            return {"mode": "mock", "status": "running"}
        if self._real_parser:
            status = "connected" if self._real_parser.is_connected else "disconnected"
            return {
                "mode": "real",
                "status": status,
                "host": self.host,
                "port": self.port,
            }
        return {
            "mode": "real",
            "status": "not_started",
            "host": self.host,
            "port": self.port,
        }

