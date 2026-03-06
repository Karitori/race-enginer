from services.telemetry_packet_registry import PACKET_TOPICS
from tools.telemetry_tools import get_engineer_tools


def test_packet_registry_covers_full_f1_25_surface():
    expected = set(range(16))
    assert expected.issubset(set(PACKET_TOPICS.keys()))


def test_engineer_toolset_includes_full_snapshot():
    tool_names = {getattr(tool, "name", "") for tool in get_engineer_tools()}
    assert "telemetry_gap" in tool_names
    assert "telemetry_car_state" in tool_names
    assert "telemetry_health" in tool_names
    assert "telemetry_full_snapshot" in tool_names
