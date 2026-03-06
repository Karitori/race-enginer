def format_gear(raw_gear: object) -> str:
    try:
        gear = int(raw_gear)
    except (TypeError, ValueError):
        return "N"
    if gear == -1:
        return "R"
    if gear == 0:
        return "N"
    return str(gear)


def format_connection_label(mode: str | None, status: str | None) -> str:
    safe_mode = (mode or "real").strip().lower()
    safe_status = (status or "unknown").strip().lower()
    return f"{safe_mode.upper()} | {safe_status.upper()}"
