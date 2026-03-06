"""
Real F1 25 UDP Telemetry Parser runtime.
Loads ctypes definitions and applies packet converters on incoming UDP payloads.
"""

import asyncio
import ctypes
import logging
import socket
import time
from typing import Optional

from services.event_bus_service import bus
from services.telemetry_ctypes_service import (
    ctypes_parser_module as _ct,
    expected_ctypes_parser_paths,
)
from services.telemetry_packet_registry import PACKET_TOPICS
from services.telemetry_packet_conversion_service import PACKET_CONVERTERS

logger = logging.getLogger(__name__)

class RealTelemetryParser:
    """
    Listens for real F1 25 UDP telemetry packets on the network.
    Parses binary packets using ctypes and converts to Pydantic models,
    publishing on the same event bus topics as the mock parser.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 20777):
        self.host = host
        self.port = port
        self._is_running = False
        self._socket: Optional[socket.socket] = None
        self._last_packet_time: float = 0.0
        self._connected = False
        self._connection_timeout = 5.0

    @property
    def is_connected(self) -> bool:
        if self._last_packet_time == 0:
            return False
        return (time.time() - self._last_packet_time) < self._connection_timeout

    async def start(self):
        if _ct is None:
            checked_paths = expected_ctypes_parser_paths()
            logger.error(
                "Cannot start real parser: ctypes packet definitions not found. "
                "Set F1_25_PARSER_PATH or place f1-25-telemetry-application in a supported path."
            )
            await bus.publish(
                "telemetry_status",
                {
                    "mode": "real",
                    "status": "error",
                    "error": "Missing F1 25 parser definitions",
                    "checked_paths": checked_paths,
                    "host": self.host,
                    "port": self.port,
                },
            )
            return

        self._is_running = True

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind((self.host, self.port))
            sock.setblocking(False)
            self._socket = sock
        except OSError as e:
            logger.error(f"Failed to bind UDP socket on {self.host}:{self.port}: {e}")
            await bus.publish(
                "telemetry_status",
                {
                    "mode": "real",
                    "status": "error",
                    "error": str(e),
                    "host": self.host,
                    "port": self.port,
                },
            )
            self._is_running = False
            return

        logger.info(f"Real Telemetry Parser listening on {self.host}:{self.port}")
        await bus.publish(
            "telemetry_status",
            {
                "mode": "real",
                "status": "listening",
                "host": self.host,
                "port": self.port,
            },
        )

        await self._listen_loop()

    def stop(self):
        self._is_running = False
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
        self._connected = False
        logger.info("Real Telemetry Parser stopped.")

    async def _listen_loop(self):
        loop = asyncio.get_running_loop()

        while self._is_running:
            try:
                data = await asyncio.wait_for(
                    loop.sock_recv(self._socket, 2048),
                    timeout=1.0,
                )
                self._last_packet_time = time.time()
                if not self._connected:
                    self._connected = True
                    logger.info("F1 25 game connected - receiving UDP packets")
                    await bus.publish(
                        "telemetry_status",
                        {
                            "mode": "real",
                            "status": "connected",
                            "host": self.host,
                            "port": self.port,
                        },
                    )
                await self._process_packet(data)

            except asyncio.TimeoutError:
                if self._connected and not self.is_connected:
                    self._connected = False
                    logger.warning("F1 25 game disconnected (no packets received)")
                    await bus.publish(
                        "telemetry_status",
                        {
                            "mode": "real",
                            "status": "disconnected",
                            "host": self.host,
                            "port": self.port,
                        },
                    )
            except asyncio.CancelledError:
                break
            except OSError:
                if self._is_running:
                    await asyncio.sleep(0.1)
            except Exception as e:
                if self._is_running:
                    logger.error(f"UDP listen error: {e}")
                    await asyncio.sleep(0.1)

    async def _process_packet(self, data: bytes):
        if len(data) < ctypes.sizeof(_ct.PacketHeader):
            return

        header = _ct.PacketHeader.from_buffer_copy(data)
        packet_id = header.m_packet_id

        packet_type = _ct.HEADER_FIELD_TO_PACKET_TYPE.get(packet_id)
        if not packet_type:
            return

        try:
            ct_packet = packet_type.from_buffer_copy(data)
        except ValueError:
            return

        topic = PACKET_TOPICS.get(packet_id)
        converter = PACKET_CONVERTERS.get(packet_id)
        if topic and converter:
            try:
                pydantic_model = converter(ct_packet)
                await bus.publish(topic, pydantic_model)
            except Exception as e:
                logger.debug(f"Conversion error for packet {packet_id}: {e}")



