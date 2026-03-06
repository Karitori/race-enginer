from utils.radio_text import to_radio_brief


def test_to_radio_brief_strips_list_formatting():
    raw = "1. Box this lap\n2. Save fuel in S1 and S3\n- Keep it clean"
    brief = to_radio_brief(raw, max_sentences=2, max_chars=160)
    assert "1." not in brief
    assert "2." not in brief
    assert "- " not in brief


def test_to_radio_brief_limits_sentences():
    raw = "Box now. Save fuel. Harvest ERS before turn one."
    brief = to_radio_brief(raw, max_sentences=2, max_chars=160)
    assert brief.count(".") <= 2
    assert "Harvest ERS" not in brief


def test_to_radio_brief_removes_markdown_noise():
    raw = "## Update\nUse **ERS** now and avoid lockups."
    brief = to_radio_brief(raw, max_sentences=2, max_chars=160)
    assert "#" not in brief
    assert "*" not in brief
    assert "ERS" in brief

