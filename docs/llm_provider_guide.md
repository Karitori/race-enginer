# LLM Provider Guide (Cost vs Quality)

Updated: 2026-03-06

## Goal
Use near-free or low-cost providers where possible, while keeping strategy/radio quality close to frontier-model behavior.

## Practical Recommendations

1. **Default low-cost cloud**: `groq + openai/gpt-oss-20b`
- Best for always-on strategy polling and voice summarization.
- Very low token pricing and fast latency.

2. **Higher-quality low-cost cloud**: `groq + openai/gpt-oss-120b`
- Use for strategy and advisor if you want stronger reasoning depth.
- Keep voice summarization on `gpt-oss-20b` to reduce cost.

3. **Free/local private option**: `ollama + qwen3`
- Zero per-token API cost, fully local.
- Quality depends on local hardware and selected model size.

## Runtime Mapping in This Repo

Environment resolution priority:
1. Role-specific envs (`STRATEGY_*`, `ADVISOR_*`, `VOICE_*`)
2. Global envs (`LLM_*`)
3. Optional `LLM_PROFILE` preset (`groq-cheap`, `groq-quality`, `local-oss`)

## Source Links

- LangChain `init_chat_model` integration index:
  https://docs.langchain.com/oss/python/integrations/chat
- Groq model and pricing pages:
  - https://console.groq.com/docs/models
  - https://console.groq.com/docs/models/openai/gpt-oss-120b
  - https://console.groq.com/docs/models/openai/gpt-oss-20b
- Ollama docs (local OSS deployment):
  https://ollama.com/
  https://docs.ollama.com/
- Together AI pricing (additional low-cost cloud OSS option):
  https://www.together.ai/pricing

