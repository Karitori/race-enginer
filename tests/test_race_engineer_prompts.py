from prompts.race_engineer_prompts import build_advisor_system_prompt


def test_advisor_prompt_includes_rebecca_identity():
    prompt = build_advisor_system_prompt(
        telemetry_context="speed=300",
        persona_name="strategist",
        persona_instruction="Persona text.",
        tone_instruction="Tone text.",
    )
    assert "Rebecca" in prompt
    assert "Becca" in prompt


def test_advisor_prompt_forces_in_character_human_role():
    prompt = build_advisor_system_prompt(
        telemetry_context="speed=300",
        persona_name="strategist",
        persona_instruction="Persona text.",
        tone_instruction="Tone text.",
    )
    assert "real human race engineer teammate" in prompt
    assert "Never break character" in prompt

