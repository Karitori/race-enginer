import asyncio
import logging
import os
import re
import tempfile
import wave
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


def _clamp_float(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _is_remote_resource(path_or_uri: str) -> bool:
    cleaned = path_or_uri.strip().lower()
    return cleaned.startswith("http://") or cleaned.startswith("https://") or cleaned.startswith(
        "hf://"
    )


def _prepare_tts_text(text: str, max_chars: int) -> str:
    """Normalize message text for faster, cleaner TTS synthesis."""
    cleaned = (text or "").replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"[`*_#~\[\]{}<>|]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"[^A-Za-z0-9 .,!?;:'%/+-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= max_chars:
        return cleaned

    clipped = cleaned[:max_chars].rsplit(" ", 1)[0].strip()
    if not clipped:
        clipped = cleaned[:max_chars].strip()
    if clipped and clipped[-1] not in ".!?":
        clipped = f"{clipped}."
    return clipped


class AudioOutputService:
    """Audio output wrapper locked to local Kokoro backend."""

    def __init__(self):
        self.backend = (os.getenv("VOICE_TTS_BACKEND", "kokoro") or "kokoro").strip().lower()
        self.enabled = _parse_bool(os.getenv("VOICE_ENABLE_TTS"), True)
        self._simulate_delay = _parse_bool(os.getenv("VOICE_SIMULATE_DELAY"), True)

        self._kokoro_model_path = (os.getenv("VOICE_KOKORO_MODEL_PATH", "") or "").strip()
        self._kokoro_voices_path = (os.getenv("VOICE_KOKORO_VOICES_PATH", "") or "").strip()
        self._kokoro_voice = (os.getenv("VOICE_KOKORO_VOICE", "af_sarah") or "af_sarah").strip()
        self._kokoro_lang = (os.getenv("VOICE_KOKORO_LANG", "en-us") or "en-us").strip()
        self._kokoro_speed = _clamp_float(
            _parse_float(os.getenv("VOICE_KOKORO_SPEED"), 1.15), 0.5, 2.0
        )
        self._tts_max_chars = max(80, int(_parse_float(os.getenv("VOICE_TTS_MAX_CHARS"), 220)))

        self._kokoro_tts: Any = None
        self._available = False
        self._setup_backend()

    @property
    def available(self) -> bool:
        return self._available

    def _setup_backend(self) -> None:
        if not self.enabled or self.backend in {"none", "off", "disabled"}:
            logger.info("audio output disabled (VOICE_ENABLE_TTS=false or backend=none)")
            return

        if self.backend != "kokoro":
            logger.warning(
                "unsupported VOICE_TTS_BACKEND=%s; only 'kokoro' is allowed, audio output disabled",
                self.backend,
            )
            return

        self._setup_kokoro()

    def _setup_kokoro(self) -> None:
        if not self._kokoro_model_path:
            logger.warning("VOICE_KOKORO_MODEL_PATH is required for kokoro backend.")
            return
        if not self._kokoro_voices_path:
            logger.warning("VOICE_KOKORO_VOICES_PATH is required for kokoro backend.")
            return
        if _is_remote_resource(self._kokoro_model_path) or _is_remote_resource(
            self._kokoro_voices_path
        ):
            logger.warning("kokoro backend is local-only; remote URIs are not allowed.")
            return
        if not os.path.isfile(self._kokoro_model_path):
            logger.warning("kokoro model file not found: %s", self._kokoro_model_path)
            return
        if not os.path.isfile(self._kokoro_voices_path):
            logger.warning("kokoro voices file not found: %s", self._kokoro_voices_path)
            return

        try:
            from kokoro_onnx import Kokoro

            # phonemizer can emit noisy word-count mismatch warnings for valid input;
            # keep it quiet unless errors occur.
            logging.getLogger("phonemizer").setLevel(logging.ERROR)

            self._kokoro_tts = Kokoro(
                model_path=self._kokoro_model_path,
                voices_path=self._kokoro_voices_path,
            )
            self._available = True
            logger.info(
                "kokoro backend enabled (voice=%s, lang=%s, speed=%.2f)",
                self._kokoro_voice,
                self._kokoro_lang,
                self._kokoro_speed,
            )
        except Exception as exc:
            logger.warning("kokoro initialization failed: %s", exc)
            self._available = False

    async def speak(self, message: str) -> None:
        prepared = _prepare_tts_text(message, self._tts_max_chars)
        if not prepared:
            return

        if self._available and self.backend == "kokoro":
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._speak_with_kokoro_sync, prepared)
            return

        if self._simulate_delay:
            await asyncio.sleep(min(len(prepared) * 0.02, 2.0))

    def _speak_with_kokoro_sync(self, message: str) -> None:
        if self._kokoro_tts is None:
            return

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            wav_path = wav_file.name

        try:
            import numpy as np

            samples, sample_rate = self._kokoro_tts.create(
                message,
                voice=self._kokoro_voice,
                speed=self._kokoro_speed,
                lang=self._kokoro_lang,
            )
            sample_array = np.asarray(samples, dtype=np.float32).flatten()
            if sample_array.size == 0:
                return

            audio_pcm = np.clip(sample_array, -1.0, 1.0)
            audio_pcm = (audio_pcm * 32767.0).astype(np.int16)

            with wave.open(wav_path, "wb") as wav_writer:
                wav_writer.setnchannels(1)
                wav_writer.setsampwidth(2)
                wav_writer.setframerate(int(sample_rate))
                wav_writer.writeframes(audio_pcm.tobytes())

            try:
                import winsound

                winsound.PlaySound(wav_path, winsound.SND_FILENAME)
            except Exception as exc:
                logger.warning("kokoro produced audio but playback failed: %s", exc)
        except Exception as exc:
            logger.error("kokoro TTS failed: %s", exc)
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

    def stop(self) -> None:
        self._kokoro_tts = None
