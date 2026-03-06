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
- LLM env vars in `.env` for advisor/voice (example: `LLM_PROVIDER=google_genai`, `LLM_MODEL=gemini-2.5-flash`)

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

## Notes

- `requirements.txt` is removed.
- Phase 2 LangGraph strategy execution now runs in-process via `agents/strategy_agent.py`.
- Default telemetry mode is now `real` (UDP listener on `0.0.0.0:20777`).
- Real UDP telemetry requires F1 25 ctypes definitions (`parser2025.py`):
  - Preferred: set `F1_25_PARSER_PATH` in `.env` to the absolute parser file path.
  - Alternative: keep `f1-25-telemetry-application` adjacent to this repo.
- Set `TELEMETRY_FALLBACK_TO_MOCK=true` only if you want automatic fallback when real parser boot fails.

