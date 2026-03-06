from utils.radio_personality import detect_driver_tone, next_rapport_level, tone_instruction


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

