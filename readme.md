# Race Engineer

Race Engineer is an AI-powered, real-time voice assistant and telemetry analyzer for Formula 1 simulations and offline analysis.

## Architecture Layout

This fork now uses root-level architecture modules with explicit ownership:
- `agents`: full LangGraph agent wiring per agent (optional when node-only flow is enough)
- `db`: database access and repositories
- `docs`: readme and project documentation
- `models`: all Pydantic models/schemas for the project
- `nodes`: all LangGraph nodes
- `prompts`: prompt templates
- `routes`: FastAPI route handlers imported by `main.py`
- `services`: shared services/factories/singletons (LLM clients, orchestration)
- `tools`: LangChain tools (`@tool`-decorated modules)
- `utils`: helper functions grouped by functionality
- `main.py`: application entry point (not a directory)
- `desktop_app`: standalone Windows overlay companion app (separate process from backend)
- `assets`: desktop app resources (icon, Windows version metadata, future branding assets)

Role-reflective file naming is now applied, for example:
- `agents/strategy_agent.py`
- `nodes/strategy_analysis_nodes.py`
- `routes/api_routes.py`, `routes/websocket_routes.py`, `routes/dashboard_routes.py`
- `services/race_engineer_service.py`, `services/voice_service.py`, `services/feedback_service.py`
- `services/telemetry_mode_service.py`, `services/http_server_service.py`
- `db/telemetry_store.py`, `db/telemetry_repository.py`
- `tools/strategy_snapshot_tool.py`
- `utils/f1_25_strategy_knowledge.py`

All project source directories are kept flat (no nested source subdirectories).

## Dependency Management

This project is now `uv` managed.

## Prerequisites

- Python 3.10+
- `uv`
- Optional: microphone/speakers for voice output
- Local Ollama runtime with `nemotron-mini:4b` model available

## Setup

```bash
uv sync
```

```bash
cp .env.example .env
```

## Run

```bash
uv run python main.py
```

## Standalone Desktop Overlay (Windows)

The overlay is intentionally separated from backend runtime so you can run/stop it independently.

1. Start backend:
```bash
uv run python main.py
```
2. Start overlay companion app (new terminal):
```bash
uv run python overlay_main.py
```

The overlay connects to backend via `http://127.0.0.1:8000` and `ws://127.0.0.1:8000/ws` by default, with settings persisted to `.overlay_settings.json`.

## Build `.exe` (Windows)

Install/update dependencies:
```bash
uv sync
```

Build windowed overlay executable (onedir):
```powershell
powershell -ExecutionPolicy Bypass -File .\build_overlay_exe.ps1
```

Build single-file executable:
```powershell
powershell -ExecutionPolicy Bypass -File .\build_overlay_exe.ps1 -OneFile
```

Optional icon:
- default icon is included at `assets/desktop_app_icon.ico`.
- replace it with your branded icon, or set `OVERLAY_ICON_PATH` in `.env`.

## Notes

- `requirements.txt` is removed.
- Phase 2 LangGraph strategy execution now runs in-process via `agents/strategy_agent.py`.
- Default telemetry mode is now `real` (UDP listener on `0.0.0.0:20777`).
- Real UDP telemetry requires F1 25 ctypes definitions (`parser2025.py`):
  - Preferred: set `F1_25_PARSER_PATH` in `.env` to the absolute parser file path.
  - Alternative: keep `f1-25-telemetry-application` adjacent to this repo.
- Set `TELEMETRY_FALLBACK_TO_MOCK=true` only if you want automatic fallback when real parser boot fails.

## LLM Choice

The app now enforces a single local LLM runtime:
- Provider: `ollama`
- Model: `nemotron-mini:4b` (NVIDIA lightweight model)

If other providers/models are configured in env, the app coerces them back to `ollama/nemotron-mini:4b`.

Temperatures can still be set globally (`LLM_TEMPERATURE`) or per role (`STRATEGY_TEMPERATURE`, etc.).

## Voice & Audio

- TTS is locked to local Kokoro:
  - `VOICE_TTS_BACKEND=kokoro`
  - `VOICE_KOKORO_MODEL_PATH=...` (required local `.onnx`)
  - `VOICE_KOKORO_VOICES_PATH=...` (required local voices `.bin`)
  - voice is now forced to `af_sarah` for consistency across all comms.
  - optional: `VOICE_KOKORO_LANG`, `VOICE_KOKORO_SPEED`, `VOICE_TTS_MAX_CHARS`
  - expressive radio tuning: `VOICE_KOKORO_EXPRESSIVE=true` plus optional per-style speed envs (`VOICE_KOKORO_SPEED_WARNING`, etc.)
- Optional mic STT is locked to Whisper Turbo via `VOICE_ENABLE_STT=true` and `VOICE_STT_BACKEND=whisper`.
  - `VOICE_STT_WHISPER_MODEL=turbo` (or a local Turbo model path)
  - optional: `VOICE_STT_WHISPER_DEVICE=cuda`, `VOICE_STT_WHISPER_COMPUTE_TYPE=float16`.
  - optional explicit input device: `VOICE_STT_MIC_INDEX=<device_index>`.
  - optional detection tuning: `VOICE_STT_DYNAMIC_ENERGY_THRESHOLD=true`, `VOICE_STT_ENERGY_THRESHOLD=300`.
  - PTT immediate capture chunk: `VOICE_STT_PTT_CHUNK_SEC=2.2`.
  - optional reliability fallback: `VOICE_STT_AUTO_CPU_FALLBACK=true` (switches to CPU/int8 if CUDA transcription errors keep happening).
  - comms control mode: `VOICE_STT_CONTROL_MODE=toggle|ptt|always` (recommended: `toggle` or `ptt`).
  - for toggle mode startup state: `VOICE_STT_TOGGLE_DEFAULT_ON=false`.
  - optional VAD filter remains configurable (`VOICE_STT_WHISPER_VAD_FILTER=false` recommended for race-radio realism).
  - dashboard includes mic controls: Toggle Mic, Hold-To-Talk, mode selector, microphone selector, and Space-key PTT binding.
  - recognized speech is shown live in comms log as `[YOU] ...` so you can verify STT capture.
  - driver barge-in is enabled: if you speak while TTS is talking, current engineer audio is interrupted and your query is prioritized.
- Voice queue summarization now uses structured LLM output instead of manual JSON parsing.
- Advisor personality now adapts to driver tone:
  - banter receives light teammate-style wit,
  - frustration gets calm supportive comms,
  - urgent/critical situations force direct serious calls.
  - personality archetype auto-switches per context (`pitwall_commander`, `calm_coach`, `dry_wit_teammate`, `strategist`, `focused_teammate`) with radio fillers for more natural TTS rhythm.

