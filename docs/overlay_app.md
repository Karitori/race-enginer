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
- UI event buffering is memory-bounded with telemetry coalescing (latest tick only).

## Build as `.exe`

- Run: `powershell -ExecutionPolicy Bypass -File .\build_overlay_exe.ps1`
- Single-file build: `powershell -ExecutionPolicy Bypass -File .\build_overlay_exe.ps1 -OneFile`
- Default icon: `assets/desktop_app_icon.ico` (replace with your branded icon if needed).
- Optional override: set `OVERLAY_ICON_PATH`.

## Standards reference

- See `docs/windows_distribution_standards.md`.
