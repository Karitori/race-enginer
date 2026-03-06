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
    r"\bhow can i assist you today\b",
    r"\bi'?m doing well,?\s*thanks for asking\b",
)


def is_out_of_character_response(text: str) -> bool:
    sample = (text or "").strip().lower()
    if not sample:
        return True
    return any(re.search(pattern, sample) for pattern in _OUT_OF_CHARACTER_PATTERNS)
