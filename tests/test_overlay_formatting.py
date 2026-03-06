from desktop_app.overlay_formatting import format_connection_label, format_gear


def test_format_gear():
    assert format_gear(0) == "N"
    assert format_gear(-1) == "R"
    assert format_gear(7) == "7"
    assert format_gear("bad") == "N"


def test_format_connection_label():
    assert format_connection_label("real", "connected") == "REAL | CONNECTED"
    assert format_connection_label("mock", "running") == "MOCK | RUNNING"
    assert format_connection_label(None, None) == "REAL | UNKNOWN"
