from prompts.race_engineer_prompts import build_advisor_system_prompt


def test_advisor_prompt_includes_rebecca_identity():
    prompt = build_advisor_system_prompt(
        telemetry_context="speed=300",
        persona_name="strategist",
        persona_instruction="Persona text.",
        tone_instruction="Tone text.",
        conversation_context="Driver: radio check\nBecca: copy",
        driver_preference_instruction="Driver preference text.",
    )
    assert "Rebecca" in prompt
    assert "Becca" in prompt


def test_advisor_prompt_forces_in_character_human_role():
    prompt = build_advisor_system_prompt(
        telemetry_context="speed=300",
        persona_name="strategist",
        persona_instruction="Persona text.",
        tone_instruction="Tone text.",
        conversation_context="Driver: radio check\nBecca: copy",
        driver_preference_instruction="Driver preference text.",
    )
    assert "real human race engineer teammate" in prompt
    assert "Never break character" in prompt


def test_advisor_prompt_requires_conversation_continuity():
    prompt = build_advisor_system_prompt(
        telemetry_context="speed=300",
        persona_name="strategist",
        persona_instruction="Persona text.",
        tone_instruction="Tone text.",
        conversation_context="Driver: hey\nBecca: copy",
        driver_preference_instruction="Driver preference text.",
    )
    assert "ongoing radio channel" in prompt
    assert "preserve continuity" in prompt
    assert "Never ask broad helper questions" in prompt
