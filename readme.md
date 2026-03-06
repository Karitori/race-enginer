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
- LLM provider package credentials in `.env` (for your selected LangChain provider)

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

The app now resolves models by role with fallback:
- `STRATEGY_PROVIDER` / `STRATEGY_MODEL`
- `ADVISOR_PROVIDER` / `ADVISOR_MODEL`
- `VOICE_PROVIDER` / `VOICE_MODEL`
- fallback to global `LLM_PROVIDER` / `LLM_MODEL`
- optional presets via `LLM_PROFILE`:
  - `groq-cheap` (`openai/gpt-oss-20b`)
  - `groq-quality` (`openai/gpt-oss-120b` for strategy/advisor)
  - `local-oss` (Ollama local models)

Temperatures can be set globally (`LLM_TEMPERATURE`) or per role (`STRATEGY_TEMPERATURE`, etc.).

## Voice & Audio

- TTS output uses `VOICE_TTS_BACKEND` (`pocket`, `piper`, `pyttsx3`, or `none`), with `VOICE_ENABLE_TTS=true|false`.
- Recommended local high-quality setup is Pocket-TTS:
  - `VOICE_TTS_BACKEND=pocket`
  - `VOICE_POCKET_CONFIG_PATH=...` (required local YAML with local weight/tokenizer paths)
  - `VOICE_POCKET_AUDIO_PROMPT_PATH=...` (required local `.wav` or `.safetensors`)
  - optional: `VOICE_POCKET_DEVICE`, `VOICE_POCKET_TEMP`, `VOICE_POCKET_MAX_TOKENS`
- Local fallback setup for Piper:
  1. Place your local Piper `.onnx` model (and `.onnx.json`) on disk.
  2. Run:
     `powershell -ExecutionPolicy Bypass -File .\configure_local_piper.ps1 -ModelPath "D:\path\voice.onnx"`
  3. Copy generated lines from `.env.piper.local` into `.env`.
- Optional mic STT is local Whisper via `VOICE_ENABLE_STT=true` and `VOICE_STT_BACKEND=whisper`.
  - `VOICE_STT_WHISPER_MODEL_PATH` is required and must point to a local Faster-Whisper model directory (for example `large-v3` converted model files).
  - optional: `VOICE_STT_WHISPER_DEVICE=cuda`, `VOICE_STT_WHISPER_COMPUTE_TYPE=float16`.
- `VOICE_STT_BACKEND=parakeet` is reserved for upcoming integration and currently logs a clear not-wired warning.
- Voice queue summarization now uses structured LLM output instead of manual JSON parsing.

