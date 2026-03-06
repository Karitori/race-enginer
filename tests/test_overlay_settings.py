from desktop_app.overlay_models import OverlaySettings
from desktop_app.overlay_settings import OverlaySettingsService


def test_overlay_settings_roundtrip(tmp_path):
    path = tmp_path / "overlay_settings.json"
    service = OverlaySettingsService(path)

    first = service.get()
    assert first.server_host == "127.0.0.1"
    assert first.server_port == 8000

    updated = OverlaySettings(
        server_host="localhost",
        server_port=9001,
        width=700,
        height=300,
        x=100,
        y=120,
        opacity=0.65,
        font_size=12,
        always_on_top=False,
        show_only_when_connected=True,
        default_talk_level=7,
    )
    service.save(updated)

    reloaded = OverlaySettingsService(path).get()
    assert reloaded.server_host == "localhost"
    assert reloaded.server_port == 9001
    assert reloaded.opacity == 0.65
    assert reloaded.default_talk_level == 7


def test_overlay_settings_invalid_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "overlay_settings.json"
    path.write_text("{not-json", encoding="utf-8")

    settings = OverlaySettingsService(path).get()
    assert settings.server_host == "127.0.0.1"
    assert settings.server_port == 8000
