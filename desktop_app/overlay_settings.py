import json
import logging
from pathlib import Path

from desktop_app.overlay_models import OverlaySettings

logger = logging.getLogger(__name__)


class OverlaySettingsService:
    """Load and persist standalone desktop overlay settings."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._settings = OverlaySettings()
        self._load()

    def get(self) -> OverlaySettings:
        return self._settings.model_copy(deep=True)

    def save(self, settings: OverlaySettings) -> OverlaySettings:
        self._settings = settings
        self._path.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
        return self.get()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._settings = OverlaySettings.model_validate(data)
        except Exception as exc:
            logger.warning(
                "Unable to load overlay settings from %s: %s",
                self._path,
                exc,
            )
            self._settings = OverlaySettings()
