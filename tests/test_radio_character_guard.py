from utils.radio_character_guard import is_out_of_character_response


def test_detects_policy_style_refusal():
    text = "I cannot provide advice on personal matters as an AI assistant."
    assert is_out_of_character_response(text) is True


def test_detects_meta_model_language():
    text = "As a language model, I am unable to do that."
    assert is_out_of_character_response(text) is True


def test_accepts_normal_engineer_line():
    text = "Copy, box this lap and protect the fronts in sector three."
    assert is_out_of_character_response(text) is False

