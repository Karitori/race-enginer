import importlib.util
import logging
import os
from types import ModuleType

logger = logging.getLogger(__name__)


def _candidate_parser_paths() -> list[str]:
    env_path = os.getenv("F1_25_PARSER_PATH")
    candidates: list[str] = []

    if env_path:
        candidates.append(os.path.abspath(env_path))

    candidates.append(
        os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "f1-25-telemetry-application",
                "src",
                "parsers",
                "parser2025.py",
            )
        )
    )
    candidates.append(
        os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "f1-25-telemetry-application",
                "src",
                "parsers",
                "parser2025.py",
            )
        )
    )

    # De-duplicate while preserving order.
    unique: list[str] = []
    for path in candidates:
        if path not in unique:
            unique.append(path)
    return unique


def resolve_ctypes_parser_path() -> str | None:
    """Return first existing parser2025.py path, if any."""
    for path in _candidate_parser_paths():
        if os.path.exists(path):
            return path
    return None


def expected_ctypes_parser_paths() -> list[str]:
    """Return parser lookup paths in priority order."""
    return _candidate_parser_paths()


def is_ctypes_parser_available() -> bool:
    return resolve_ctypes_parser_path() is not None


def load_ctypes_parser_module() -> ModuleType | None:
    """Load external F1 25 ctypes packet definitions module if present."""
    parser_path = resolve_ctypes_parser_path()
    if parser_path is None:
        logger.warning(
            "Reference F1 25 parser not found. Checked paths: %s",
            ", ".join(expected_ctypes_parser_paths()),
        )
        return None

    spec = importlib.util.spec_from_file_location("_f1_ctypes", parser_path)
    if spec is None or spec.loader is None:
        logger.warning("Unable to load parser module spec from %s", parser_path)
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ctypes_parser_module = load_ctypes_parser_module()
