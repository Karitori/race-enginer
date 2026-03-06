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


def _parse_optional_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    if cleaned == "":
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


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
        self.control_mode = (
            os.getenv("VOICE_STT_CONTROL_MODE", "toggle") or "toggle"
        ).strip().lower()
        self.language = os.getenv("VOICE_STT_LANGUAGE", "en")
        self.timeout_sec = _parse_float(os.getenv("VOICE_STT_TIMEOUT_SEC"), 4.0)
        self.phrase_limit_sec = _parse_float(os.getenv("VOICE_STT_PHRASE_LIMIT_SEC"), 6.0)
        self.ambient_sec = _parse_float(os.getenv("VOICE_STT_AMBIENT_SEC"), 0.4)
        self.ptt_chunk_sec = _parse_float(os.getenv("VOICE_STT_PTT_CHUNK_SEC"), 2.2)
        self.mic_index = _parse_optional_int(os.getenv("VOICE_STT_MIC_INDEX"))
        self.dynamic_energy_threshold = _parse_bool(
            os.getenv("VOICE_STT_DYNAMIC_ENERGY_THRESHOLD"), True
        )
        self.energy_threshold = _parse_optional_int(os.getenv("VOICE_STT_ENERGY_THRESHOLD"))
        self.auto_cpu_fallback = _parse_bool(os.getenv("VOICE_STT_AUTO_CPU_FALLBACK"), True)

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
        self.whisper_vad_filter = _parse_bool(os.getenv("VOICE_STT_WHISPER_VAD_FILTER"), False)

        self._running = False
        self._available = False
        self._sr: Any = None
        self._recognizer: Any = None
        self._microphone: Any = None
        self._whisper_model: Any = None
        self._whisper_model_cls: Any = None
        self._whisper_model_ref: str = "turbo"
        self._ambient_calibrated = False
        self._mic_name = "default"
        self._last_error: str | None = None
        self._gate_wait_logged = False
        self._capture_error_count = 0
        self._transcribe_error_count = 0
        self._cpu_fallback_activated = False
        self._toggle_active = _parse_bool(os.getenv("VOICE_STT_TOGGLE_DEFAULT_ON"), False)
        self._ptt_pressed = False
        self._setup_backend()

    @property
    def available(self) -> bool:
        return self._available and self.enabled

    def _setup_backend(self) -> None:
        self.control_mode = self._normalize_control_mode(self.control_mode)
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

    @staticmethod
    def _normalize_control_mode(raw: str | None) -> str:
        mode = (raw or "").strip().lower()
        if mode in {"toggle", "ptt", "always"}:
            return mode
        return "toggle"

    @staticmethod
    def list_microphone_names() -> list[str]:
        try:
            import speech_recognition as sr  # type: ignore

            names = sr.Microphone.list_microphone_names()
            return [str(name) for name in names]
        except Exception:
            return []

    def _resolve_mic_name(self) -> str:
        names = self.list_microphone_names()
        if self.mic_index is None:
            return "default"
        if 0 <= self.mic_index < len(names):
            return names[self.mic_index]
        return f"index:{self.mic_index}"

    def _build_microphone(self) -> None:
        if not self._sr:
            self._microphone = None
            return
        try:
            if self.mic_index is None:
                self._microphone = self._sr.Microphone()
            else:
                self._microphone = self._sr.Microphone(device_index=self.mic_index)
            self._mic_name = self._resolve_mic_name()
        except Exception as exc:
            self._last_error = f"failed to initialize microphone index {self.mic_index}: {exc}"
            logger.warning("%s", self._last_error)
            self.mic_index = None
            self._microphone = self._sr.Microphone()
            self._mic_name = "default"

    def _is_capture_gate_open(self) -> bool:
        if self.control_mode == "always":
            return True
        if self.control_mode == "ptt":
            return self._ptt_pressed
        return self._toggle_active

    def get_control_status(self) -> dict[str, Any]:
        gate_open = self._is_capture_gate_open()
        return {
            "enabled": self.enabled,
            "available": self._available,
            "backend": self.backend,
            "whisper_device": self.whisper_device,
            "whisper_compute_type": self.whisper_compute_type,
            "mic_index": self.mic_index,
            "mic_name": self._mic_name,
            "control_mode": self.control_mode,
            "toggle_active": self._toggle_active,
            "ptt_pressed": self._ptt_pressed,
            "capture_gate_open": gate_open,
            "capture_active": gate_open and self.available,
            "last_error": self._last_error,
            "capture_errors": self._capture_error_count,
            "transcribe_errors": self._transcribe_error_count,
            "cpu_fallback_activated": self._cpu_fallback_activated,
        }

    def apply_control_action(
        self,
        *,
        action: str,
        enabled: bool | None = None,
        mode: str | None = None,
        mic_index: int | None = None,
    ) -> dict[str, Any]:
        normalized_action = (action or "").strip().lower()
        if normalized_action == "toggle":
            self._toggle_active = not self._toggle_active
        elif normalized_action == "set":
            if enabled is not None:
                self._toggle_active = bool(enabled)
        elif normalized_action == "ptt_down":
            self._ptt_pressed = True
        elif normalized_action == "ptt_up":
            self._ptt_pressed = False
        elif normalized_action == "mode":
            self.control_mode = self._normalize_control_mode(mode)
        elif normalized_action == "set_mic":
            self.mic_index = None if mic_index is None or mic_index < 0 else int(mic_index)
            self._ambient_calibrated = False
            if self._sr is not None:
                self._build_microphone()
            else:
                self._mic_name = self._resolve_mic_name()
        elif normalized_action == "reset":
            self._toggle_active = _parse_bool(os.getenv("VOICE_STT_TOGGLE_DEFAULT_ON"), False)
            self._ptt_pressed = False
            self._last_error = None
            self._capture_error_count = 0
            self._transcribe_error_count = 0
        return self.get_control_status()

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
            self._whisper_model_cls = WhisperModel
            self._recognizer = sr.Recognizer()
            self._recognizer.dynamic_energy_threshold = self.dynamic_energy_threshold
            if self.energy_threshold is not None:
                self._recognizer.energy_threshold = max(10, self.energy_threshold)
            self._build_microphone()
            if not self._initialize_whisper_model():
                self._available = False
                return

            self._available = self._whisper_model is not None
            logger.info(
                (
                    "whisper turbo STT backend enabled "
                    "(model=%s, device=%s, compute_type=%s, mic=%s, dynamic_energy=%s, energy=%s, auto_cpu_fallback=%s)"
                ),
                self._whisper_model_ref,
                self.whisper_device,
                self.whisper_compute_type,
                self._mic_name,
                self.dynamic_energy_threshold,
                self._recognizer.energy_threshold if self._recognizer else "n/a",
                self.auto_cpu_fallback,
            )
        except Exception as exc:
            logger.warning("whisper STT initialization failed: %s", exc)
            self._available = False

    def _initialize_whisper_model(self) -> bool:
        if self._whisper_model_cls is None:
            self._last_error = "whisper model class unavailable"
            return False
        try:
            self._whisper_model = self._whisper_model_cls(
                model_size_or_path=self._whisper_model_ref,
                device=self.whisper_device,
                compute_type=self.whisper_compute_type,
                local_files_only=True,
            )
            return True
        except Exception as exc:
            self._last_error = f"whisper model init failed: {exc}"
            logger.warning("whisper model init failed (%s/%s): %s", self.whisper_device, self.whisper_compute_type, exc)
            self._whisper_model = None
            return False

    def _activate_cpu_fallback(self) -> bool:
        if not self.auto_cpu_fallback or self._cpu_fallback_activated:
            return False
        if self.whisper_device != "cuda":
            return False
        logger.warning(
            "stt cuda path unstable; attempting fallback to cpu/int8 for reliability."
        )
        self.whisper_device = "cpu"
        self.whisper_compute_type = "int8"
        self._cpu_fallback_activated = True
        ok = self._initialize_whisper_model()
        if ok:
            logger.warning("stt cpu fallback activated successfully.")
            return True
        logger.error("stt cpu fallback failed; STT remains unavailable.")
        self._available = False
        return False

    async def run(
        self,
        on_transcript: Callable[[str, float], Awaitable[None]],
    ) -> None:
        if not self.available:
            return

        self._running = True
        loop = asyncio.get_running_loop()
        while self._running:
            if not self._is_capture_gate_open():
                if not self._gate_wait_logged:
                    logger.info(
                        "stt capture paused (mode=%s). open mic via toggle/PTT to listen.",
                        self.control_mode,
                    )
                    self._gate_wait_logged = True
                await asyncio.sleep(0.04)
                continue
            if self._gate_wait_logged:
                logger.info("stt capture gate opened; listening.")
                self._gate_wait_logged = False
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
                if self.control_mode == "ptt":
                    # PTT should capture immediately without waiting for voice trigger.
                    chunk_sec = max(0.5, min(self.ptt_chunk_sec, max(0.5, self.phrase_limit_sec)))
                    audio = self._recognizer.record(source, duration=chunk_sec)
                else:
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
            self._capture_error_count += 1
            self._last_error = f"stt capture error: {exc}"
            if self._capture_error_count <= 2 or self._capture_error_count % 10 == 0:
                logger.warning("stt capture error (%d): %s", self._capture_error_count, exc)
            else:
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
            self._last_error = None
            self._transcribe_error_count = 0
            return text, confidence
        except Exception as exc:
            self._transcribe_error_count += 1
            self._last_error = f"whisper transcription error: {exc}"
            if self._transcribe_error_count <= 2 or self._transcribe_error_count % 5 == 0:
                logger.warning(
                    "whisper transcription error (%d, device=%s/%s): %s",
                    self._transcribe_error_count,
                    self.whisper_device,
                    self.whisper_compute_type,
                    exc,
                )
            else:
                logger.debug("whisper transcription error: %s", exc)

            if self._activate_cpu_fallback():
                self._last_error = "switched to cpu/int8 fallback after cuda transcription failures"
            return None
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

    def stop(self) -> None:
        self._running = False
        self._whisper_model = None
