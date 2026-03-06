# Desktop Overlay App

The desktop overlay is a separate process under `desktop_app/` to keep backend concerns and UI concerns isolated.

## Run

1. Start backend:
   - `uv run python main.py`
2. Start overlay:
   - `uv run python overlay_main.py`

## Connection

- HTTP: `http://127.0.0.1:8000` (configurable)
- WebSocket: `ws://127.0.0.1:8000/ws`

## Persistence

- Settings are saved to `.overlay_settings.json` by default.
- Override path with `OVERLAY_SETTINGS_FILE`.
