import asyncio
import logging
import os
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
        return int(raw)
    except ValueError:
        return default


def _parse_float(raw: str | None, default: float) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


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


class AudioOutputService:
    """Audio output wrapper locked to local Pocket-TTS backend."""

    def __init__(self):
        self.backend = (os.getenv("VOICE_TTS_BACKEND", "pocket") or "pocket").strip().lower()
        self.enabled = _parse_bool(os.getenv("VOICE_ENABLE_TTS"), True)
        self._simulate_delay = _parse_bool(os.getenv("VOICE_SIMULATE_DELAY"), True)

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

        if self.backend != "pocket":
            logger.warning(
                "unsupported VOICE_TTS_BACKEND=%s; only 'pocket' is allowed, audio output disabled",
                self.backend,
            )
            return

        self._setup_pocket()

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

        if self._available and self.backend == "pocket":
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._speak_with_pocket_sync, message)
            return

        if self._simulate_delay:
            await asyncio.sleep(min(len(message) * 0.03, 3.0))

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
        self._pocket_voice_state = None
        self._pocket_model = None
