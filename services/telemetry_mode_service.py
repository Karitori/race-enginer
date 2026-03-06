import asyncio
import logging
import os
from typing import Any

from services.event_bus_service import bus
from services.mock_telemetry_service import BaseTelemetryParser
from services.telemetry_ctypes_service import (
    expected_ctypes_parser_paths,
    is_ctypes_parser_available,
)

logger = logging.getLogger(__name__)


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _parse_port(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    return value


class TelemetryModeService:
    """Manage switching between mock and real telemetry runtime services."""

    def __init__(self):
        configured_mode = (os.getenv("TELEMETRY_MODE", "real") or "real").strip().lower()
        if configured_mode not in ("mock", "real"):
            logger.warning("Invalid TELEMETRY_MODE=%s, defaulting to real", configured_mode)
            configured_mode = "real"

        self.mode = configured_mode
        self.host = os.getenv("TELEMETRY_HOST", "0.0.0.0")
        self.port = _parse_port(os.getenv("TELEMETRY_PORT"), 20777)
        self.fallback_to_mock = _parse_bool(os.getenv("TELEMETRY_FALLBACK_TO_MOCK"), False)

        self._mock_parser: BaseTelemetryParser | None = None
        self._real_parser = None
        self._active_task: asyncio.Task[Any] | None = None
        self._is_running = False
        self._last_error: str | None = None

    async def start(self):
        self._is_running = True
        await self.switch_mode(self.mode, self.host, self.port)

        while self._is_running:
            await self._monitor_real_parser_health()
            await asyncio.sleep(0.5)

    async def switch_mode(
        self, mode: str, host: str | None = None, port: int | None = None
    ):
        requested_mode = mode.strip().lower()
        if requested_mode not in ("mock", "real"):
            raise ValueError("Mode must be 'mock' or 'real'")

        previous_mode = self.mode
        if host is not None:
            self.host = host
        if port is not None:
            self.port = int(port)

        should_restart = (
            requested_mode != self.mode
            or self._active_task is None
            or self._active_task.done()
            or host is not None
            or port is not None
        )
        if not should_restart:
            return

        await self._stop_active_parser()
        self.mode = requested_mode
        self._last_error = None

        if requested_mode == "mock":
            await self._start_mock()
            logger.info("Telemetry mode switched %s -> mock", previous_mode)
            return

        await self._start_real_or_error(previous_mode=previous_mode)

    async def _start_mock(self) -> None:
        self._mock_parser = BaseTelemetryParser()
        self._active_task = asyncio.create_task(self._mock_parser.start())
        await bus.publish("telemetry_status", {"mode": "mock", "status": "running"})

    async def _start_real_or_error(self, previous_mode: str) -> None:
        if not is_ctypes_parser_available():
            self._last_error = "Missing F1 25 parser definitions (parser2025.py)"
            logger.error(
                "Real telemetry unavailable. Checked paths: %s",
                ", ".join(expected_ctypes_parser_paths()),
            )
            await bus.publish(
                "telemetry_status",
                {
                    "mode": "real",
                    "status": "error",
                    "error": self._last_error,
                    "host": self.host,
                    "port": self.port,
                },
            )
            if self.fallback_to_mock:
                logger.warning("Falling back to mock telemetry mode.")
                self.mode = "mock"
                await self._start_mock()
            return

        from services.real_telemetry_service import RealTelemetryParser

        self._real_parser = RealTelemetryParser(host=self.host, port=self.port)
        self._active_task = asyncio.create_task(self._real_parser.start())
        await bus.publish(
            "telemetry_status",
            {
                "mode": "real",
                "status": "starting",
                "host": self.host,
                "port": self.port,
            },
        )
        logger.info(
            "Telemetry mode switched %s -> real (%s:%s)",
            previous_mode,
            self.host,
            self.port,
        )

    async def _monitor_real_parser_health(self) -> None:
        if self.mode != "real":
            return
        if self._active_task is None or not self._active_task.done():
            return

        failed = not self._active_task.cancelled()
        if failed:
            try:
                exc = self._active_task.exception()
            except Exception as err:  # pragma: no cover - defensive
                exc = err
            if exc:
                self._last_error = str(exc)
            elif not self._last_error:
                self._last_error = "Real telemetry parser stopped unexpectedly"

        self._active_task = None
        self._real_parser = None

        if failed and self.fallback_to_mock:
            logger.warning("Real parser stopped. Falling back to mock mode.")
            self.mode = "mock"
            await self._start_mock()

    async def _stop_active_parser(self):
        if self._mock_parser is not None:
            self._mock_parser.stop()
        if self._real_parser is not None:
            self._real_parser.stop()

        if self._active_task is not None and not self._active_task.done():
            self._active_task.cancel()
            try:
                await self._active_task
            except asyncio.CancelledError:
                pass

        self._active_task = None
        self._mock_parser = None
        self._real_parser = None

    def stop(self):
        self._is_running = False
        if self._mock_parser is not None:
            self._mock_parser.stop()
        if self._real_parser is not None:
            self._real_parser.stop()
        if self._active_task is not None and not self._active_task.done():
            self._active_task.cancel()

    def get_status(self) -> dict[str, Any]:
        if self.mode == "mock":
            status = "running" if self._active_task and not self._active_task.done() else "stopped"
            return {"mode": "mock", "status": status}

        if self._last_error:
            return {
                "mode": "real",
                "status": "error",
                "error": self._last_error,
                "host": self.host,
                "port": self.port,
            }

        if self._active_task and not self._active_task.done() and self._real_parser:
            status = "connected" if self._real_parser.is_connected else "listening"
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

