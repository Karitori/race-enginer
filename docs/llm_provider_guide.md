# LLM Runtime Guide (Locked Configuration)

Updated: 2026-03-06

## Policy

This project is intentionally locked to a single local LLM target:

- Provider: `ollama`
- Model: `nemotron-mini:4b` (NVIDIA lightweight model)

Any other configured provider/model is ignored and coerced back to this pair.

## Required Runtime

1. Install and run Ollama locally.
2. Pull the model:
   - `ollama pull nemotron-mini:4b`
3. Keep `.env` aligned:
   - `LLM_PROVIDER=ollama`
   - `LLM_MODEL=nemotron-mini:4b`

## Notes

- Role-specific provider/model env overrides are no longer used.
- Only temperature remains role-tunable (`STRATEGY_TEMPERATURE`, `ADVISOR_TEMPERATURE`, `VOICE_TEMPERATURE`).
- STT and TTS remain local-only:
  - STT: NVIDIA Parakeet (default) or Canary (optional), with Whisper as legacy fallback
  - TTS: Kokoro via `kokoro-onnx`
