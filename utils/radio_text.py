import re

_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*]+|\d+[.)]|[A-Za-z][.)])\s+")
_MARKDOWN_RE = re.compile(r"[`*_#~\[\]{}<>|]")
_SPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_LEADING_CHATTER_RE = re.compile(
    r"^(?:here(?:'s| is)\s+(?:the|your)\s+(?:plan|update|summary)\s*[:\-]\s*)",
    flags=re.IGNORECASE,
)


def to_radio_brief(
    text: str,
    *,
    max_sentences: int = 2,
    max_chars: int = 180,
) -> str:
    """Normalize free-form text into compact race-radio phrasing."""
    if not text:
        return ""

    lines: list[str] = []
    for raw_line in text.replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        line = _LIST_PREFIX_RE.sub("", line)
        lines.append(line)

    if not lines:
        return ""

    merged = " ".join(lines)
    merged = _MARKDOWN_RE.sub(" ", merged).replace(";", ". ")
    merged = _SPACE_RE.sub(" ", merged).strip(" -:,.")
    merged = _LEADING_CHATTER_RE.sub("", merged).strip()
    if not merged:
        return ""

    chunks = [chunk.strip(" -:,.") for chunk in _SENTENCE_SPLIT_RE.split(merged)]
    chunks = [chunk for chunk in chunks if chunk]
    if max_sentences > 0 and len(chunks) > max_sentences:
        chunks = chunks[:max_sentences]

    brief = " ".join(chunks).strip()
    if not brief:
        return ""

    if len(brief) > max_chars:
        clipped = brief[:max_chars].rsplit(" ", 1)[0].strip()
        brief = clipped or brief[:max_chars].strip()

    if brief and brief[-1] not in ".!?":
        brief = f"{brief}."
    return brief

