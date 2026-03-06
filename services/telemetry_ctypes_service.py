import importlib.util
import logging
import os
from types import ModuleType

logger = logging.getLogger(__name__)


def load_ctypes_parser_module() -> ModuleType | None:
    """Load external F1 25 ctypes packet definitions module if present."""
    parser_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "f1-25-telemetry-application",
        "src",
        "parsers",
        "parser2025.py",
    )
    parser_path = os.path.abspath(parser_path)
    if not os.path.exists(parser_path):
        logger.warning("Reference F1 25 parser not found at %s", parser_path)
        return None

    spec = importlib.util.spec_from_file_location("_f1_ctypes", parser_path)
    if spec is None or spec.loader is None:
        logger.warning("Unable to load parser module spec from %s", parser_path)
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ctypes_parser_module = load_ctypes_parser_module()

