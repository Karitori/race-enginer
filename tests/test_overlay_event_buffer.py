from desktop_app.overlay_event_buffer import OverlayEventBuffer


def test_telemetry_is_coalesced_to_latest_only():
    buffer = OverlayEventBuffer(max_queue_size=10)

    for i in range(500):
        buffer.push("telemetry_tick", {"speed": i})

    batch = buffer.pop_batch(limit=10)
    telemetry_events = [item for item in batch if item[0] == "telemetry_tick"]
    assert len(telemetry_events) == 1
    assert telemetry_events[0][1]["speed"] == 499


def test_non_telemetry_queue_is_bounded():
    buffer = OverlayEventBuffer(max_queue_size=3)

    buffer.push("driving_insight", {"id": 1})
    buffer.push("driving_insight", {"id": 2})
    buffer.push("driving_insight", {"id": 3})
    buffer.push("driving_insight", {"id": 4})

    batch = buffer.pop_batch(limit=10)
    ids = [payload["id"] for topic, payload in batch if topic == "driving_insight"]
    assert len(ids) <= 3
    assert 4 in ids


def test_clear_empties_buffer():
    buffer = OverlayEventBuffer(max_queue_size=3)
    buffer.push("telemetry_tick", {"speed": 100})
    buffer.push("driving_insight", {"id": 1})
    buffer.clear()
    assert buffer.pop_batch(limit=10) == []
