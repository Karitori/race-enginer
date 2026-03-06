import asyncio
import json
import logging
from collections.abc import Callable
from contextlib import suppress

import httpx
import websockets

logger = logging.getLogger(__name__)


class OverlayClientService:
    """Standalone network client for overlay process (HTTP + WebSocket)."""

    def __init__(
        self,
        host: str,
        port: int,
        on_event: Callable[[str, dict], None],
        reconnect_delay_sec: float = 1.0,
    ):
        self._host = host
        self._port = port
        self._on_event = on_event
        self._reconnect_delay_sec = reconnect_delay_sec

        self._stop_event: asyncio.Event | None = None
        self._client: httpx.AsyncClient | None = None
        self._ws_task: asyncio.Task | None = None
        self._status_task: asyncio.Task | None = None

    @property
    def base_http_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def websocket_url(self) -> str:
        return f"ws://{self._host}:{self._port}/ws"

    async def run(self) -> None:
        self._stop_event = asyncio.Event()
        timeout = httpx.Timeout(connect=1.0, read=2.0, write=2.0, pool=2.0)
        self._client = httpx.AsyncClient(base_url=self.base_http_url, timeout=timeout)
        self._ws_task = asyncio.create_task(self._websocket_loop())
        self._status_task = asyncio.create_task(self._telemetry_status_poll_loop())

        try:
            await self._stop_event.wait()
        finally:
            if self._ws_task:
                self._ws_task.cancel()
            if self._status_task:
                self._status_task.cancel()
            with suppress(asyncio.CancelledError):
                if self._ws_task:
                    await self._ws_task
            with suppress(asyncio.CancelledError):
                if self._status_task:
                    await self._status_task
            if self._client is not None:
                await self._client.aclose()
                self._client = None

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    async def send_driver_query(self, query_text: str) -> None:
        if self._client is None:
            return
        try:
            await self._client.post("/api/driver_query", json={"query": query_text})
        except Exception as exc:
            logger.warning("Failed to send driver query: %s", exc)

    async def send_talk_level(self, talk_level: int) -> None:
        if self._client is None:
            return
        try:
            await self._client.post("/api/talk_level", json={"talk_level": talk_level})
        except Exception as exc:
            logger.warning("Failed to send talk level: %s", exc)

    async def _websocket_loop(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(self.websocket_url, ping_interval=20) as ws:
                    self._on_event(
                        "overlay_connection",
                        {"connected": True, "target": self.websocket_url},
                    )
                    async for raw in ws:
                        if self._stop_event.is_set():
                            break
                        try:
                            message = json.loads(raw)
                        except Exception:
                            continue
                        topic = message.get("topic")
                        payload = message.get("payload")
                        if isinstance(topic, str) and isinstance(payload, dict):
                            self._on_event(topic, payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._on_event(
                    "overlay_connection",
                    {"connected": False, "error": str(exc)},
                )
                await asyncio.sleep(self._reconnect_delay_sec)

    async def _telemetry_status_poll_loop(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            if self._client is not None:
                try:
                    response = await self._client.get("/api/telemetry_status")
                    if response.status_code == 200:
                        data = response.json()
                        if isinstance(data, dict):
                            self._on_event("telemetry_status", data)
                except Exception:
                    pass
            await asyncio.sleep(2.0)
