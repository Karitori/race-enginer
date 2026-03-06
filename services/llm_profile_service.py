import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMProfile:
    role: str
    provider: str | None
    model: str | None
    temperature: float
    source: str


_PROFILE_PRESETS: dict[str, dict[str, dict[str, str] | float]] = {
    # Lowest-cost practical default for high-throughput iterations.
    "groq-cheap": {
        "strategy": {"provider": "groq", "model": "openai/gpt-oss-20b"},
        "advisor": {"provider": "groq", "model": "openai/gpt-oss-20b"},
        "voice": {"provider": "groq", "model": "openai/gpt-oss-20b"},
        "temperature": 0.2,
    },
    # Higher quality open-weight option while keeping cost low vs frontier closed models.
    "groq-quality": {
        "strategy": {"provider": "groq", "model": "openai/gpt-oss-120b"},
        "advisor": {"provider": "groq", "model": "openai/gpt-oss-120b"},
        "voice": {"provider": "groq", "model": "openai/gpt-oss-20b"},
        "temperature": 0.2,
    },
    # Local/private option (requires local hardware via Ollama).
    "local-oss": {
        "strategy": {"provider": "ollama", "model": "qwen3:30b"},
        "advisor": {"provider": "ollama", "model": "qwen3:30b"},
        "voice": {"provider": "ollama", "model": "qwen3:8b"},
        "temperature": 0.2,
    },
}


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value is None:
            continue
        text = value.strip()
        if text:
            return text
    return None


def _read_env(*names: str) -> str | None:
    return _first_non_empty(*(os.getenv(name) for name in names))


def _has_env_pair(name_a: str, name_b: str) -> bool:
    return _read_env(name_a) is not None and _read_env(name_b) is not None


def _parse_temperature(raw: str | None, default: float) -> float:
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(0.0, min(2.0, value))


def resolve_llm_profile(role: str, default_temperature: float) -> LLMProfile:
    """Resolve role-specific provider/model/temperature with global fallback."""
    key = role.strip().upper()
    preset_key = (os.getenv("LLM_PROFILE") or "").strip().lower()
    preset = _PROFILE_PRESETS.get(preset_key)
    preset_role = None
    if preset:
        preset_role = preset.get(role.lower())
        if not isinstance(preset_role, dict):
            preset_role = None

    provider = _read_env(
        f"{key}_PROVIDER",
        f"{key}_LLM_PROVIDER",
        "LLM_PROVIDER",
    )
    if provider is None and preset_role is not None:
        provider = _first_non_empty(preset_role.get("provider"))

    model = _read_env(
        f"{key}_MODEL",
        f"{key}_LLM_MODEL",
        "LLM_MODEL",
    )
    if model is None and preset_role is not None:
        model = _first_non_empty(preset_role.get("model"))

    preset_temperature = None
    if preset and isinstance(preset.get("temperature"), (float, int)):
        preset_temperature = float(preset["temperature"])
    temperature = _parse_temperature(
        _read_env(
            f"{key}_TEMPERATURE",
            f"{key}_LLM_TEMPERATURE",
            "LLM_TEMPERATURE",
        ),
        default=preset_temperature if preset_temperature is not None else default_temperature,
    )

    if _has_env_pair(f"{key}_PROVIDER", f"{key}_MODEL"):
        source = f"{key}_PROVIDER/{key}_MODEL"
    elif _has_env_pair(f"{key}_LLM_PROVIDER", f"{key}_LLM_MODEL"):
        source = f"{key}_LLM_PROVIDER/{key}_LLM_MODEL"
    elif _has_env_pair("LLM_PROVIDER", "LLM_MODEL"):
        source = "LLM_PROVIDER/LLM_MODEL"
    elif preset and provider and model:
        source = f"LLM_PROFILE:{preset_key}"
    else:
        source = "unset"

    return LLMProfile(
        role=role,
        provider=provider,
        model=model,
        temperature=temperature,
        source=source,
    )
