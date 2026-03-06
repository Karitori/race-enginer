import re

_OUT_OF_CHARACTER_PATTERNS = (
    r"\bas an ai\b",
    r"\bi am an ai\b",
    r"\bi'm an ai\b",
    r"\blanguage model\b",
    r"\bpolicy\b",
    r"\bi cannot\b",
    r"\bi can't\b",
    r"\bi am unable\b",
    r"\bi'm unable\b",
    r"\bnot able to\b",
    r"\bcannot provide advice on personal matters\b",
    r"\bpersonal matters\b",
    r"\bi do not have\b",
    r"\bi don't have\b",
    r"\bhow can i assist(?: you)?(?: today)?\b",
    r"\bhow can i help(?: you)?(?: today)?\b",
    r"\bwhat do you need help with\b",
    r"\bwhat can i do for you\b",
    r"\bwhat do you need from me\b",
    r"\bmy current focus is\b",
    r"\bi'?m doing well,?\s*thanks for asking\b",
    r"\bi'?m doing well,?\s*thank you\b",
    r"\bi'?m sorry,?\s*but i cannot\b",
    r"\bsure thing\b",
    r"\bi can help with that\b",
)


def is_out_of_character_response(text: str) -> bool:
    sample = (text or "").strip().lower()
    if not sample:
        return True
    return any(re.search(pattern, sample) for pattern in _OUT_OF_CHARACTER_PATTERNS)
