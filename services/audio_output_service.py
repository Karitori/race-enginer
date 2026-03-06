import asyncio
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import wave
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


def _parse_optional_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    if cleaned == "":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _clamp_float(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _is_remote_resource(path_or_uri: str) -> bool:
    cleaned = path_or_uri.strip().lower()
    return cleaned.startswith("http://") or cleaned.startswith("https://") or cleaned.startswith(
        "hf://"
    )


def _default_torch_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


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
        self.backend = (os.getenv("VOICE_TTS_BACKEND", "pocket") or "pocket").strip().lower()
        self.enabled = _parse_bool(os.getenv("VOICE_ENABLE_TTS"), True)
        self.rate = _parse_int(os.getenv("VOICE_TTS_RATE"), 170)
        self.volume = _clamp_float(_parse_float(os.getenv("VOICE_TTS_VOLUME"), 1.0), 0.0, 1.0)
        self.pyttsx3_voice_hint = (os.getenv("VOICE_PYTTS3_VOICE_HINT", "") or "").strip()
        self._simulate_delay = _parse_bool(os.getenv("VOICE_SIMULATE_DELAY"), True)
        self._piper_extra_args = _parse_piper_extra_args(os.getenv("VOICE_PIPER_EXTRA_ARGS"))
        self._pocket_device = (
            os.getenv("VOICE_POCKET_DEVICE", _default_torch_device()) or _default_torch_device()
        ).strip()
        self._pocket_temp = _parse_float(os.getenv("VOICE_POCKET_TEMP"), 0.7)
        self._pocket_lsd_decode_steps = max(
            1, _parse_int(os.getenv("VOICE_POCKET_LSD_DECODE_STEPS"), 6)
        )
        self._pocket_noise_clamp = _parse_optional_float(os.getenv("VOICE_POCKET_NOISE_CLAMP"))
        self._pocket_eos_threshold = _parse_float(os.getenv("VOICE_POCKET_EOS_THRESHOLD"), -3.0)
        self._pocket_max_tokens = max(32, _parse_int(os.getenv("VOICE_POCKET_MAX_TOKENS"), 180))
        self._pocket_copy_state = _parse_bool(os.getenv("VOICE_POCKET_COPY_STATE"), True)
        self._pocket_truncate_prompt = _parse_bool(
            os.getenv("VOICE_POCKET_TRUNCATE_PROMPT"), True
        )

        self._engine: Any = None
        self._piper_executable: str | None = None
        self._piper_model_path: str | None = None
        self._piper_speaker_id: int | None = None
        self._pocket_model: Any = None
        self._pocket_voice_state: Any = None
        self._pocket_sample_rate: int = 24_000
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

        if self.backend == "pocket":
            self._setup_pocket()
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

    def _setup_pocket(self) -> None:
        config_path = (os.getenv("VOICE_POCKET_CONFIG_PATH", "") or "").strip()
        audio_prompt_path = (os.getenv("VOICE_POCKET_AUDIO_PROMPT_PATH", "") or "").strip()

        if not config_path:
            logger.warning("VOICE_POCKET_CONFIG_PATH is required for pocket backend.")
            return
        if not audio_prompt_path:
            logger.warning("VOICE_POCKET_AUDIO_PROMPT_PATH is required for pocket backend.")
            return
        if _is_remote_resource(config_path) or _is_remote_resource(audio_prompt_path):
            logger.warning("pocket backend is local-only; remote URIs are not allowed.")
            return
        if not os.path.isfile(config_path):
            logger.warning("pocket config not found: %s", config_path)
            return
        if not os.path.isfile(audio_prompt_path):
            logger.warning("pocket audio prompt not found: %s", audio_prompt_path)
            return

        try:
            config_text = ""
            with open(config_path, encoding="utf-8") as cfg:
                config_text = cfg.read()
            if "hf://" in config_text or "http://" in config_text or "https://" in config_text:
                logger.warning(
                    "pocket config must use local weight/tokenizer paths only: %s",
                    config_path,
                )
                return
        except OSError as exc:
            logger.warning("could not read pocket config file: %s", exc)
            return

        try:
            from pocket_tts import TTSModel

            model = TTSModel.load_model(
                config=config_path,
                temp=self._pocket_temp,
                lsd_decode_steps=self._pocket_lsd_decode_steps,
                noise_clamp=self._pocket_noise_clamp,
                eos_threshold=self._pocket_eos_threshold,
            )
            model = model.to(self._pocket_device)
            model.eval()
            voice_state = model.get_state_for_audio_prompt(
                audio_prompt_path,
                truncate=self._pocket_truncate_prompt,
            )
        except Exception as exc:
            logger.warning("pocket-tts initialization failed: %s", exc)
            return

        self._pocket_model = model
        self._pocket_voice_state = voice_state
        self._pocket_sample_rate = int(getattr(model, "sample_rate", 24_000))
        self._available = True
        logger.info(
            "pocket backend enabled (device=%s, config=%s, sample_rate=%d)",
            self._pocket_device,
            config_path,
            self._pocket_sample_rate,
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
        if self._available and self.backend == "pocket":
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._speak_with_pocket_sync, message)
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

    def _speak_with_pocket_sync(self, message: str) -> None:
        if self._pocket_model is None or self._pocket_voice_state is None:
            return

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            wav_path = wav_file.name

        try:
            import numpy as np

            audio = self._pocket_model.generate_audio(
                model_state=self._pocket_voice_state,
                text_to_generate=message,
                max_tokens=self._pocket_max_tokens,
                copy_state=self._pocket_copy_state,
            )
            if audio is None:
                return
            if hasattr(audio, "detach"):
                audio = audio.detach().cpu()

            audio_array = np.asarray(audio, dtype=np.float32).flatten()
            if audio_array.size == 0:
                return
            audio_pcm = np.clip(audio_array, -1.0, 1.0)
            audio_pcm = (audio_pcm * 32767.0).astype(np.int16)

            with wave.open(wav_path, "wb") as wav_writer:
                wav_writer.setnchannels(1)
                wav_writer.setsampwidth(2)
                wav_writer.setframerate(self._pocket_sample_rate)
                wav_writer.writeframes(audio_pcm.tobytes())

            try:
                import winsound

                winsound.PlaySound(wav_path, winsound.SND_FILENAME)
            except Exception as exc:
                logger.warning("pocket-tts produced audio but playback failed: %s", exc)
        except Exception as exc:
            logger.error("pocket-tts failed: %s", exc)
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

    def stop(self) -> None:
        if self._engine is not None:
            try:
                self._engine.stop()  # type: ignore
            except Exception:
                pass
        self._pocket_voice_state = None
        self._pocket_model = None
