import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _parse_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value


class AudioOutputService:
    """Audio output wrapper that supports pluggable TTS backends."""

    def __init__(self):
        self.backend = (os.getenv("VOICE_TTS_BACKEND", "pyttsx3") or "pyttsx3").strip().lower()
        self.enabled = _parse_bool(os.getenv("VOICE_ENABLE_TTS"), True)
        self.rate = _parse_int(os.getenv("VOICE_TTS_RATE"), 170)
        self._simulate_delay = _parse_bool(os.getenv("VOICE_SIMULATE_DELAY"), True)

        self._engine: Any = None
        self._available = False
        self._setup_backend()

    @property
    def available(self) -> bool:
        return self._available

    def _setup_backend(self) -> None:
        if not self.enabled or self.backend in {"none", "off", "disabled"}:
            logger.info("audio output disabled (VOICE_ENABLE_TTS=false or backend=none)")
            return

        if self.backend != "pyttsx3":
            logger.warning("unsupported VOICE_TTS_BACKEND=%s; audio output disabled", self.backend)
            return

        try:
            import pyttsx3  # type: ignore

            self._engine = pyttsx3.init()  # type: ignore
            self._engine.setProperty("rate", self.rate)  # type: ignore
            self._available = True
        except Exception as exc:
            logger.warning("pyttsx3 initialization failed: %s", exc)
            self._engine = None
            self._available = False

    async def speak(self, message: str) -> None:
        if not message:
            return

        if self._available and self._engine is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._speak_sync, message)
            return

        if self._simulate_delay:
            await asyncio.sleep(min(len(message) * 0.03, 3.0))

    def _speak_sync(self, message: str) -> None:
        if self._engine is None:
            return
        try:
            self._engine.say(message)  # type: ignore
            self._engine.runAndWait()  # type: ignore
        except Exception as exc:
            logger.error("tts backend error: %s", exc)

    def stop(self) -> None:
        if self._engine is None:
            return
        try:
            self._engine.stop()  # type: ignore
        except Exception:
            pass

