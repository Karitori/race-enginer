from pathlib import Path


def read_text_file(path: Path, encoding: str = "utf-8") -> str:
    return path.read_text(encoding=encoding)
