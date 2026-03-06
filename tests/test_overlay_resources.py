from desktop_app.overlay_resources import get_overlay_icon_path, resolve_runtime_path


def test_resolve_runtime_path_returns_cwd_relative():
    resolved = resolve_runtime_path("overlay_main.py")
    assert resolved.name == "overlay_main.py"


def test_get_overlay_icon_path_returns_none_for_missing(monkeypatch):
    monkeypatch.setenv("OVERLAY_ICON_PATH", "missing_icon.ico")
    assert get_overlay_icon_path() is None


def test_get_overlay_icon_path_returns_existing_file(tmp_path, monkeypatch):
    icon_path = tmp_path / "sample.ico"
    icon_path.write_bytes(b"\x00\x00\x01\x00")
    monkeypatch.setenv("OVERLAY_ICON_PATH", str(icon_path))
    resolved = get_overlay_icon_path()
    assert resolved == icon_path
