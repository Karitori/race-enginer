import os
import sys
from pathlib import Path


def resolve_runtime_path(relative_path: str) -> Path:
    """
    Resolve resource paths for both source runs and PyInstaller bundles.
    """
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / relative_path
    return Path.cwd() / relative_path


def get_overlay_icon_path() -> Path | None:
    icon_path = os.getenv("OVERLAY_ICON_PATH", "assets/desktop_app_icon.ico").strip()
    if not icon_path:
        return None

    resolved = resolve_runtime_path(icon_path)
    if resolved.exists():
        return resolved
    return None
