from services.llm_profile_service import resolve_llm_profile


def test_role_specific_llm_profile_overrides_global(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "global_provider")
    monkeypatch.setenv("LLM_MODEL", "global_model")
    monkeypatch.setenv("STRATEGY_PROVIDER", "strategy_provider")
    monkeypatch.setenv("STRATEGY_MODEL", "strategy_model")
    monkeypatch.setenv("STRATEGY_TEMPERATURE", "0.55")

    profile = resolve_llm_profile("strategy", default_temperature=0.2)
    assert profile.provider == "strategy_provider"
    assert profile.model == "strategy_model"
    assert profile.temperature == 0.55
    assert profile.source == "STRATEGY_PROVIDER/STRATEGY_MODEL"


def test_role_profile_falls_back_to_global(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "global_provider")
    monkeypatch.setenv("LLM_MODEL", "global_model")
    monkeypatch.delenv("VOICE_PROVIDER", raising=False)
    monkeypatch.delenv("VOICE_MODEL", raising=False)

    profile = resolve_llm_profile("voice", default_temperature=0.2)
    assert profile.provider == "global_provider"
    assert profile.model == "global_model"
    assert profile.temperature == 0.2
    assert profile.source == "LLM_PROVIDER/LLM_MODEL"


def test_temperature_clamped_and_defaulted(monkeypatch):
    monkeypatch.setenv("ADVISOR_PROVIDER", "p")
    monkeypatch.setenv("ADVISOR_MODEL", "m")
    monkeypatch.setenv("ADVISOR_TEMPERATURE", "99")
    profile_high = resolve_llm_profile("advisor", default_temperature=0.1)
    assert profile_high.temperature == 2.0

    monkeypatch.setenv("ADVISOR_TEMPERATURE", "bad-number")
    profile_bad = resolve_llm_profile("advisor", default_temperature=0.33)
    assert profile_bad.temperature == 0.33


def test_profile_preset_applies_when_env_unset(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("STRATEGY_PROVIDER", raising=False)
    monkeypatch.delenv("STRATEGY_MODEL", raising=False)
    monkeypatch.setenv("LLM_PROFILE", "groq-cheap")

    profile = resolve_llm_profile("strategy", default_temperature=0.7)
    assert profile.provider == "groq"
    assert profile.model == "openai/gpt-oss-20b"
    assert profile.temperature == 0.2
    assert profile.source == "LLM_PROFILE:groq-cheap"
