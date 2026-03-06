import asyncio
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
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


def _parse_float(raw: str | None, default: float) -> float:
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value


def _clamp_float(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _voice_text(voice: Any) -> str:
    parts: list[str] = []
    for attr in ("id", "name", "gender"):
        value = getattr(voice, attr, "")
        if value:
            parts.append(str(value))
    languages = getattr(voice, "languages", [])
    if isinstance(languages, (list, tuple)):
        for language in languages:
            if isinstance(language, bytes):
                parts.append(language.decode("utf-8", errors="ignore"))
            else:
                parts.append(str(language))
    return " ".join(parts).lower()


def _select_pyttsx3_voice_id(voices: list[Any], hint: str | None = None) -> str | None:
    if not voices:
        return None

    cleaned_hint = (hint or "").strip().lower()
    if cleaned_hint:
        for voice in voices:
            if cleaned_hint in _voice_text(voice):
                return getattr(voice, "id", None)

    preferred_tokens = [
        "jenny",
        "aria",
        "zira",
        "hazel",
        "susan",
        "guy",
        "david",
    ]
    for token in preferred_tokens:
        for voice in voices:
            if token in _voice_text(voice):
                return getattr(voice, "id", None)

    return getattr(voices[0], "id", None)


def _parse_piper_extra_args(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        return [arg.strip() for arg in shlex.split(raw, posix=False) if arg.strip()]
    except ValueError:
        return []


class AudioOutputService:
    """Audio output wrapper that supports pluggable TTS backends."""

    def __init__(self):
        self.backend = (os.getenv("VOICE_TTS_BACKEND", "pyttsx3") or "pyttsx3").strip().lower()
        self.enabled = _parse_bool(os.getenv("VOICE_ENABLE_TTS"), True)
        self.rate = _parse_int(os.getenv("VOICE_TTS_RATE"), 170)
        self.volume = _clamp_float(_parse_float(os.getenv("VOICE_TTS_VOLUME"), 1.0), 0.0, 1.0)
        self.pyttsx3_voice_hint = (os.getenv("VOICE_PYTTS3_VOICE_HINT", "") or "").strip()
        self._simulate_delay = _parse_bool(os.getenv("VOICE_SIMULATE_DELAY"), True)
        self._piper_extra_args = _parse_piper_extra_args(os.getenv("VOICE_PIPER_EXTRA_ARGS"))

        self._engine: Any = None
        self._piper_executable: str | None = None
        self._piper_model_path: str | None = None
        self._piper_speaker_id: int | None = None
        self._available = False
        self._setup_backend()

    @property
    def available(self) -> bool:
        return self._available

    def _setup_backend(self) -> None:
        if not self.enabled or self.backend in {"none", "off", "disabled"}:
            logger.info("audio output disabled (VOICE_ENABLE_TTS=false or backend=none)")
            return

        if self.backend == "pyttsx3":
            self._setup_pyttsx3()
            return

        if self.backend == "piper":
            self._setup_piper()
            return

        logger.warning("unsupported VOICE_TTS_BACKEND=%s; audio output disabled", self.backend)

    def _setup_pyttsx3(self) -> None:
        try:
            import pyttsx3  # type: ignore

            self._engine = pyttsx3.init()  # type: ignore
            self._engine.setProperty("rate", self.rate)  # type: ignore
            self._engine.setProperty("volume", self.volume)  # type: ignore
            voices = self._engine.getProperty("voices") or []  # type: ignore
            selected_voice_id = _select_pyttsx3_voice_id(
                list(voices), self.pyttsx3_voice_hint
            )
            if selected_voice_id:
                self._engine.setProperty("voice", selected_voice_id)  # type: ignore
            self._available = True
            logger.info(
                "pyttsx3 backend enabled (rate=%d, volume=%.2f, voice=%s)",
                self.rate,
                self.volume,
                selected_voice_id or "default",
            )
        except Exception as exc:
            logger.warning("pyttsx3 initialization failed: %s", exc)
            self._engine = None
            self._available = False

    def _setup_piper(self) -> None:
        executable = (os.getenv("VOICE_PIPER_EXE", "piper") or "piper").strip()
        model_path = (os.getenv("VOICE_PIPER_MODEL_PATH", "") or "").strip()
        speaker_raw = (os.getenv("VOICE_PIPER_SPEAKER_ID", "") or "").strip()

        if not model_path:
            logger.warning("VOICE_PIPER_MODEL_PATH is required for piper backend.")
            return

        resolved_executable = shutil.which(executable)
        if resolved_executable is None:
            logger.warning(
                "piper executable not found (VOICE_PIPER_EXE=%s); audio output disabled",
                executable,
            )
            return

        if not os.path.exists(model_path):
            logger.warning("piper model not found: %s", model_path)
            return

        speaker_id: int | None = None
        if speaker_raw:
            try:
                speaker_id = int(speaker_raw)
            except ValueError:
                logger.warning(
                    "invalid VOICE_PIPER_SPEAKER_ID=%s; ignoring speaker selection",
                    speaker_raw,
                )
                speaker_id = None

        self._piper_executable = resolved_executable
        self._piper_model_path = model_path
        self._piper_speaker_id = speaker_id
        self._available = True
        logger.info(
            "piper backend enabled with model=%s extra_args=%s",
            model_path,
            " ".join(self._piper_extra_args) if self._piper_extra_args else "(none)",
        )

    async def speak(self, message: str) -> None:
        if not message:
            return

        if self._available and self._engine is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._speak_sync, message)
            return
        if self._available and self.backend == "piper":
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._speak_with_piper_sync, message)
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

    def _speak_with_piper_sync(self, message: str) -> None:
        if not self._piper_executable or not self._piper_model_path:
            return

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            wav_path = wav_file.name

        try:
            command = [
                self._piper_executable,
                "--model",
                self._piper_model_path,
                "--output_file",
                wav_path,
            ]
            if self._piper_speaker_id is not None:
                command.extend(["--speaker", str(self._piper_speaker_id)])
            if self._piper_extra_args:
                command.extend(self._piper_extra_args)

            subprocess.run(
                command,
                input=message.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )

            try:
                import winsound

                winsound.PlaySound(wav_path, winsound.SND_FILENAME)
            except Exception as exc:
                logger.warning("piper produced audio but playback failed: %s", exc)
        except subprocess.CalledProcessError as exc:
            logger.error("piper TTS failed (exit=%s): %s", exc.returncode, exc.stderr)
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

    def stop(self) -> None:
        if self._engine is None:
            return
        try:
            self._engine.stop()  # type: ignore
        except Exception:
            pass
