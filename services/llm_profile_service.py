import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMProfile:
    role: str
    provider: str | None
    model: str | None
    temperature: float
    source: str


FORCED_LLM_PROVIDER = "ollama"
FORCED_LLM_MODEL = "nemotron-mini:4b"
_MODEL_ALIASES = {
    "nemotron-mini",
    "nemotron-mini:latest",
    "nemotron-mini:4b",
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


def enforce_single_local_model(
    provider: str | None,
    model: str | None,
) -> tuple[str, str, bool]:
    raw_provider = (provider or "").strip().lower()
    raw_model = (model or "").strip().lower()

    coerced = False
    if raw_provider and raw_provider != FORCED_LLM_PROVIDER:
        coerced = True
    if raw_model and raw_model not in _MODEL_ALIASES:
        coerced = True

    return FORCED_LLM_PROVIDER, FORCED_LLM_MODEL, coerced


def _parse_temperature(raw: str | None, default: float) -> float:
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(0.0, min(2.0, value))


def resolve_llm_profile(role: str, default_temperature: float) -> LLMProfile:
    """Resolve role-specific temperature and force one local Ollama model."""
    key = role.strip().upper()
    raw_provider = _read_env(
        f"{key}_PROVIDER",
        f"{key}_LLM_PROVIDER",
        "LLM_PROVIDER",
    )

    raw_model = _read_env(
        f"{key}_MODEL",
        f"{key}_LLM_MODEL",
        "LLM_MODEL",
    )

    provider, model, coerced = enforce_single_local_model(raw_provider, raw_model)

    temperature = _parse_temperature(
        _read_env(
            f"{key}_TEMPERATURE",
            f"{key}_LLM_TEMPERATURE",
            "LLM_TEMPERATURE",
        ),
        default=default_temperature,
    )

    if coerced:
        source = "forced_single_local_model"
    elif _has_env_pair(f"{key}_PROVIDER", f"{key}_MODEL") or _has_env_pair(
        f"{key}_LLM_PROVIDER",
        f"{key}_LLM_MODEL",
    ):
        source = f"{key}_PROVIDER/{key}_MODEL"
    elif _has_env_pair("LLM_PROVIDER", "LLM_MODEL"):
        source = "LLM_PROVIDER/LLM_MODEL"
    else:
        source = "default_single_local_model"

    return LLMProfile(
        role=role,
        provider=provider,
        model=model,
        temperature=temperature,
        source=source,
    )
