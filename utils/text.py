def strip_markdown_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```json"):
        stripped = stripped.split("```json", 1)[1]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    elif stripped.startswith("```"):
        stripped = stripped.split("```", 1)[1]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()
