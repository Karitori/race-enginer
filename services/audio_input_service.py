import asyncio
import logging
import os
import tempfile
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


def _parse_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _is_remote_resource(path_or_uri: str) -> bool:
    cleaned = path_or_uri.strip().lower()
    return cleaned.startswith("http://") or cleaned.startswith("https://") or cleaned.startswith(
        "hf://"
    )


def _looks_like_path(raw: str) -> bool:
    return "\\" in raw or "/" in raw or ":" in raw


def _default_torch_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


class AudioInputService:
    """Optional microphone listener that publishes STT transcripts."""

    def __init__(self):
        self.enabled = _parse_bool(os.getenv("VOICE_ENABLE_STT"), False)
        self.backend = (os.getenv("VOICE_STT_BACKEND", "whisper") or "").strip().lower()
        self.language = os.getenv("VOICE_STT_LANGUAGE", "en")
        self.timeout_sec = _parse_float(os.getenv("VOICE_STT_TIMEOUT_SEC"), 4.0)
        self.phrase_limit_sec = _parse_float(os.getenv("VOICE_STT_PHRASE_LIMIT_SEC"), 6.0)
        self.ambient_sec = _parse_float(os.getenv("VOICE_STT_AMBIENT_SEC"), 0.4)

        self.whisper_model = (os.getenv("VOICE_STT_WHISPER_MODEL", "turbo") or "turbo").strip()
        self.whisper_device = (
            os.getenv("VOICE_STT_WHISPER_DEVICE", _default_torch_device())
            or _default_torch_device()
        ).strip()
        self.whisper_compute_type = (
            os.getenv(
                "VOICE_STT_WHISPER_COMPUTE_TYPE",
                "float16" if self.whisper_device == "cuda" else "int8",
            )
            or "int8"
        ).strip()
        self.whisper_beam_size = max(1, _parse_int(os.getenv("VOICE_STT_WHISPER_BEAM_SIZE"), 1))
        self.whisper_vad_filter = _parse_bool(os.getenv("VOICE_STT_WHISPER_VAD_FILTER"), True)

        self._running = False
        self._available = False
        self._sr: Any = None
        self._recognizer: Any = None
        self._microphone: Any = None
        self._whisper_model: Any = None
        self._whisper_model_ref: str = "turbo"
        self._ambient_calibrated = False
        self._setup_backend()

    @property
    def available(self) -> bool:
        return self._available and self.enabled

    def _setup_backend(self) -> None:
        if not self.enabled:
            logger.info("audio input disabled (VOICE_ENABLE_STT=false)")
            return

        if self.backend == "whisper":
            self._setup_whisper()
            return

        logger.warning(
            "unsupported VOICE_STT_BACKEND=%s; only 'whisper' is allowed, STT disabled",
            self.backend,
        )

    def _setup_whisper(self) -> None:
        model_value = self.whisper_model
        if not model_value:
            logger.warning("VOICE_STT_WHISPER_MODEL must be set to 'turbo' or a local turbo path.")
            return
        if _is_remote_resource(model_value):
            logger.warning("whisper backend is local-only; remote model URIs are not allowed.")
            return

        if _looks_like_path(model_value):
            if not os.path.exists(model_value):
                logger.warning("whisper model path not found: %s", model_value)
                return
            self._whisper_model_ref = model_value
        else:
            model_key = model_value.lower()
            if model_key not in {"turbo", "large-v3-turbo"}:
                logger.warning(
                    "unsupported VOICE_STT_WHISPER_MODEL=%s; only Whisper Turbo is allowed",
                    model_value,
                )
                return
            self._whisper_model_ref = "turbo"

        try:
            import speech_recognition as sr  # type: ignore
            from faster_whisper import WhisperModel  # type: ignore

            self._sr = sr
            self._recognizer = sr.Recognizer()
            self._microphone = sr.Microphone()
            self._whisper_model = WhisperModel(
                model_size_or_path=self._whisper_model_ref,
                device=self.whisper_device,
                compute_type=self.whisper_compute_type,
                local_files_only=True,
            )
            self._available = True
            logger.info(
                "whisper turbo STT backend enabled (model=%s, device=%s, compute_type=%s)",
                self._whisper_model_ref,
                self.whisper_device,
                self.whisper_compute_type,
            )
        except Exception as exc:
            logger.warning("whisper STT initialization failed: %s", exc)
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

            if self.backend == "whisper":
                return self._transcribe_with_whisper(audio)

            return None
        except self._sr.WaitTimeoutError:
            return None
        except self._sr.UnknownValueError:
            return None
        except Exception as exc:
            logger.debug("stt capture error: %s", exc)
            return None

    def _transcribe_with_whisper(self, audio: Any) -> tuple[str, float] | None:
        if self._whisper_model is None:
            return None

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            wav_path = wav_file.name

        try:
            wav_bytes = audio.get_wav_data(convert_rate=16000, convert_width=2)
            with open(wav_path, "wb") as output_wav:
                output_wav.write(wav_bytes)

            segments, info = self._whisper_model.transcribe(
                wav_path,
                language=self.language or None,
                beam_size=self.whisper_beam_size,
                vad_filter=self.whisper_vad_filter,
                condition_on_previous_text=False,
                word_timestamps=False,
                temperature=0.0,
            )
            segment_list = list(segments)
            text = " ".join(segment.text.strip() for segment in segment_list if segment.text).strip()
            if not text:
                return None

            language_probability = float(getattr(info, "language_probability", 0.75))
            avg_logprob = (
                sum(segment.avg_logprob for segment in segment_list) / len(segment_list)
                if segment_list
                else -0.5
            )
            logprob_conf = max(0.0, min(1.0, 1.0 + avg_logprob))
            confidence = max(0.0, min(1.0, 0.5 * language_probability + 0.5 * logprob_conf))
            return text, confidence
        except Exception as exc:
            logger.debug("whisper transcription error: %s", exc)
            return None
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

    def stop(self) -> None:
        self._running = False
        self._whisper_model = None
