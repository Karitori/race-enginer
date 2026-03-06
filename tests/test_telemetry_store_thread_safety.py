import threading

import pytest

from db.telemetry_store import TelemetryStore
from models.telemetry import TelemetryTick


@pytest.mark.asyncio
async def test_telemetry_store_handles_concurrent_query_and_inserts():
    store = TelemetryStore(":memory:")
    tick = TelemetryTick(
        speed=220.0,
        gear=7,
        throttle=0.9,
        brake=0.0,
        steering=0.01,
        engine_rpm=11800,
        tire_wear_fl=12.0,
        tire_wear_fr=11.8,
        tire_wear_rl=14.1,
        tire_wear_rr=13.9,
        lap=3,
        track_position=0.42,
        sector=2,
    )

    stop_event = threading.Event()
    reader_errors: list[Exception] = []

    def reader() -> None:
        while not stop_event.is_set():
            try:
                store.query("SELECT COUNT(*) FROM telemetry")
            except Exception as exc:  # pragma: no cover - regression guard
                reader_errors.append(exc)
                break

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    try:
        for _ in range(120):
            await store._handle_tick(tick)
    finally:
        stop_event.set()
        reader_thread.join(timeout=1.0)
        store.close()

    assert not reader_errors
