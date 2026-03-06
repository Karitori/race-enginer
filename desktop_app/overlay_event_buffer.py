import queue
import threading
from contextlib import suppress


class OverlayEventBuffer:
    """
    Memory-bounded event buffer for overlay UI updates.
    - Coalesces high-frequency telemetry ticks to latest-only.
    - Bounds non-telemetry queue size and drops oldest entries when saturated.
    """

    def __init__(self, max_queue_size: int = 300):
        self._queue: queue.Queue[tuple[str, dict]] = queue.Queue(maxsize=max_queue_size)
        self._latest_telemetry: dict | None = None
        self._telemetry_lock = threading.Lock()

    def push(self, topic: str, payload: dict) -> None:
        if topic == "telemetry_tick":
            with self._telemetry_lock:
                self._latest_telemetry = payload
            return

        try:
            self._queue.put_nowait((topic, payload))
        except queue.Full:
            with suppress(queue.Empty):
                self._queue.get_nowait()
            with suppress(queue.Full):
                self._queue.put_nowait((topic, payload))

    def pop_batch(self, limit: int = 40) -> list[tuple[str, dict]]:
        batch: list[tuple[str, dict]] = []

        with self._telemetry_lock:
            if self._latest_telemetry is not None:
                batch.append(("telemetry_tick", self._latest_telemetry))
                self._latest_telemetry = None

        for _ in range(limit):
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return batch

    def clear(self) -> None:
        with self._telemetry_lock:
            self._latest_telemetry = None

        while True:
            with suppress(queue.Empty):
                self._queue.get_nowait()
                continue
            break
