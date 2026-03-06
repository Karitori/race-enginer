import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _parse_float(raw: str | None, default: float) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class AudioInputService:
    """Optional microphone listener that publishes STT transcripts."""

    def __init__(self):
        self.enabled = _parse_bool(os.getenv("VOICE_ENABLE_STT"), False)
        self.backend = (os.getenv("VOICE_STT_BACKEND", "speech_recognition") or "").strip().lower()
        self.language = os.getenv("VOICE_STT_LANGUAGE", "en-US")
        self.timeout_sec = _parse_float(os.getenv("VOICE_STT_TIMEOUT_SEC"), 4.0)
        self.phrase_limit_sec = _parse_float(os.getenv("VOICE_STT_PHRASE_LIMIT_SEC"), 6.0)
        self.ambient_sec = _parse_float(os.getenv("VOICE_STT_AMBIENT_SEC"), 0.4)

        self._running = False
        self._available = False
        self._sr: Any = None
        self._recognizer: Any = None
        self._microphone: Any = None
        self._ambient_calibrated = False
        self._setup_backend()

    @property
    def available(self) -> bool:
        return self._available and self.enabled

    def _setup_backend(self) -> None:
        if not self.enabled:
            logger.info("audio input disabled (VOICE_ENABLE_STT=false)")
            return

        if self.backend != "speech_recognition":
            logger.warning("unsupported VOICE_STT_BACKEND=%s; STT disabled", self.backend)
            return

        try:
            import speech_recognition as sr  # type: ignore

            self._sr = sr
            self._recognizer = sr.Recognizer()
            self._microphone = sr.Microphone()
            self._available = True
        except Exception as exc:
            logger.warning("speech recognition initialization failed: %s", exc)
            self._available = False

    async def run(
        self,
        on_transcript: Callable[[str, float], Awaitable[None]],
    ) -> None:
        if not self.available:
            return

        self._running = True
        loop = asyncio.get_running_loop()
        while self._running:
            result = await loop.run_in_executor(None, self._listen_once)
            if result is None:
                continue
            text, confidence = result
            if text:
                await on_transcript(text, confidence)

    def _listen_once(self) -> tuple[str, float] | None:
        if not self._recognizer or not self._microphone or not self._sr:
            return None

        try:
            with self._microphone as source:
                if not self._ambient_calibrated:
                    self._recognizer.adjust_for_ambient_noise(
                        source,
                        duration=max(0.0, self.ambient_sec),
                    )
                    self._ambient_calibrated = True

                audio = self._recognizer.listen(
                    source,
                    timeout=max(0.1, self.timeout_sec),
                    phrase_time_limit=max(0.5, self.phrase_limit_sec),
                )

            text = self._recognizer.recognize_google(audio, language=self.language)
            return text.strip(), 0.85
        except self._sr.WaitTimeoutError:
            return None
        except self._sr.UnknownValueError:
            return None
        except self._sr.RequestError as exc:
            logger.debug("stt request error: %s", exc)
            return None
        except Exception as exc:
            logger.debug("stt capture error: %s", exc)
            return None

    def stop(self) -> None:
        self._running = False

