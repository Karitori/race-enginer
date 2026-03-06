from utils.radio_personality import (
    apply_persona_fillers,
    choose_engineer_persona,
    detect_driver_tone,
    next_rapport_level,
    persona_instruction,
    tone_instruction,
)


def test_detect_driver_tone_banter():
    assert detect_driver_tone("haha that was a nice overtake, joke with me") == "banter"


def test_detect_driver_tone_urgent_overrides_banter():
    assert detect_driver_tone("lol but help now, got damage") == "urgent"


def test_detect_driver_tone_frustrated():
    assert detect_driver_tone("this is so annoying, i am struggling with grip") == "frustrated"


def test_next_rapport_level_clamps():
    assert next_rapport_level(5, "banter") == 5
    assert next_rapport_level(0, "urgent") == 0


def test_tone_instruction_critical_forces_urgent():
    text = tone_instruction("banter", rapport_level=5, strategy_critical=True)
    assert "No jokes" in text


def test_choose_engineer_persona_switches_to_commander_on_critical():
    persona = choose_engineer_persona(
        "neutral",
        rapport_level=2,
        strategy_criticality=5,
        speed_kph=210.0,
        lap=12,
    )
    assert persona == "pitwall_commander"


def test_choose_engineer_persona_uses_dry_wit_for_banter():
    persona = choose_engineer_persona(
        "banter",
        rapport_level=3,
        strategy_criticality=2,
        speed_kph=180.0,
        lap=15,
    )
    assert persona == "dry_wit_teammate"


def test_apply_persona_fillers_adds_radio_prefix():
    styled = apply_persona_fillers(
        "Push now and protect rear traction.",
        persona="strategist",
        tone="neutral",
        strategy_critical=False,
        rapport_level=2,
    )
    assert styled != "Push now and protect rear traction."
    assert "," in styled


def test_persona_instruction_contains_persona_identity():
    text = persona_instruction("calm_coach")
    assert "calm coach" in text.lower()
