from services.llm_profile_service import (
    FORCED_LLM_MODEL,
    FORCED_LLM_PROVIDER,
    resolve_llm_profile,
)


def test_defaults_to_forced_local_llm_when_env_unset(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("STRATEGY_PROVIDER", raising=False)
    monkeypatch.delenv("STRATEGY_MODEL", raising=False)

    profile = resolve_llm_profile("strategy", default_temperature=0.2)
    assert profile.provider == FORCED_LLM_PROVIDER
    assert profile.model == FORCED_LLM_MODEL
    assert profile.temperature == 0.2
    assert profile.source == "default_single_local_model"


def test_forces_single_local_model_even_if_global_is_different(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "global_provider")
    monkeypatch.setenv("LLM_MODEL", "global_model")

    profile = resolve_llm_profile("strategy", default_temperature=0.2)
    assert profile.provider == FORCED_LLM_PROVIDER
    assert profile.model == FORCED_LLM_MODEL
    assert profile.source == "forced_single_local_model"


def test_model_alias_is_accepted_and_normalized(monkeypatch):
    monkeypatch.setenv("VOICE_PROVIDER", "ollama")
    monkeypatch.setenv("VOICE_MODEL", "nemotron-mini")

    profile = resolve_llm_profile("voice", default_temperature=0.2)
    assert profile.provider == FORCED_LLM_PROVIDER
    assert profile.model == FORCED_LLM_MODEL
    assert profile.temperature == 0.2
    assert profile.source == "VOICE_PROVIDER/VOICE_MODEL"


def test_temperature_clamped_and_defaulted(monkeypatch):
    monkeypatch.setenv("ADVISOR_PROVIDER", "ollama")
    monkeypatch.setenv("ADVISOR_MODEL", "nemotron-mini:4b")
    monkeypatch.setenv("ADVISOR_TEMPERATURE", "99")
    profile_high = resolve_llm_profile("advisor", default_temperature=0.1)
    assert profile_high.temperature == 2.0

    monkeypatch.setenv("ADVISOR_TEMPERATURE", "bad-number")
    profile_bad = resolve_llm_profile("advisor", default_temperature=0.33)
    assert profile_bad.temperature == 0.33
