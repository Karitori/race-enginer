import asyncio
import logging
import os
import threading
from concurrent.futures import Future
from contextlib import suppress

from desktop_app.overlay_client import OverlayClientService
from desktop_app.overlay_models import OverlaySettings
from desktop_app.overlay_settings import OverlaySettingsService
from desktop_app.overlay_window import OverlayWindowService

logger = logging.getLogger(__name__)


class OverlayApp:
    """Standalone Windows overlay client process for the Race Engineer backend."""

    def __init__(self) -> None:
        settings_file = os.getenv("OVERLAY_SETTINGS_FILE", ".overlay_settings.json")
        self._settings_service = OverlaySettingsService(settings_file)
        self._settings = self._settings_service.get()
        host_override = os.getenv("OVERLAY_SERVER_HOST")
        port_override = os.getenv("OVERLAY_SERVER_PORT")
        if host_override or port_override:
            updates: dict[str, object] = {}
            if host_override:
                updates["server_host"] = host_override
            if port_override:
                try:
                    updates["server_port"] = int(port_override)
                except ValueError:
                    pass
            if updates:
                self._settings = self._settings.model_copy(update=updates)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._client: OverlayClientService | None = None
        self._stop_requested = threading.Event()
        self._network_ready = threading.Event()

        self._window = OverlayWindowService(
            settings=self._settings,
            on_query=self._send_driver_query,
            on_talk_level_changed=self._set_talk_level,
            on_settings_saved=self._save_settings,
            on_close_requested=self.stop,
        )

    def run(self) -> None:
        self._start_network_thread()
        try:
            self._window.run()
        finally:
            self.stop()

    def stop(self) -> None:
        if self._stop_requested.is_set():
            return
        self._stop_requested.set()
        self._stop_network_thread()

    def _start_network_thread(self) -> None:
        self._network_ready.clear()
        self._loop_thread = threading.Thread(
            target=self._network_thread_main,
            name="overlay-network",
            daemon=True,
        )
        self._loop_thread.start()
        self._network_ready.wait(timeout=3.0)

    def _stop_network_thread(self) -> None:
        if self._loop is not None and self._client is not None:
            try:
                future = asyncio.run_coroutine_threadsafe(self._client.stop(), self._loop)
                future.result(timeout=2.0)
            except Exception as exc:
                logger.debug("Overlay client stop signal failed: %s", exc)
        if self._loop_thread is not None and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=3.0)
        self._loop_thread = None
        self._client = None
        self._loop = None

    def _restart_network_thread(self) -> None:
        self._stop_network_thread()
        if not self._stop_requested.is_set():
            self._start_network_thread()

    def _network_thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._client = OverlayClientService(
            host=self._settings.server_host,
            port=self._settings.server_port,
            on_event=self._window.enqueue_event,
        )
        self._network_ready.set()
        try:
            loop.run_until_complete(self._client.run())
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    def _send_driver_query(self, text: str) -> None:
        if not text.strip():
            return
        self._schedule_client_call(lambda: self._client.send_driver_query(text))

    def _set_talk_level(self, talk_level: int) -> None:
        self._schedule_client_call(lambda: self._client.send_talk_level(talk_level))

    def _schedule_client_call(self, factory) -> Future | None:
        if self._loop is None or self._client is None:
            return None
        coroutine = factory()
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)

        def _consume_result(done_future: Future) -> None:
            with suppress(Exception):
                _ = done_future.result()

        future.add_done_callback(_consume_result)
        return future

    def _save_settings(self, settings: OverlaySettings) -> OverlaySettings:
        previous = self._settings
        self._settings = self._settings_service.save(settings)

        if (
            previous.server_host != self._settings.server_host
            or previous.server_port != self._settings.server_port
        ):
            self._restart_network_thread()

        return self._settings
