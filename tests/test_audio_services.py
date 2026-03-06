import pytest

from services.audio_input_service import AudioInputService
from services.audio_output_service import AudioOutputService


def test_audio_input_disabled_by_default(monkeypatch):
    monkeypatch.delenv("VOICE_ENABLE_STT", raising=False)
    service = AudioInputService()
    assert not service.available


def test_audio_input_whisper_disabled_without_model_path(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_STT", "true")
    monkeypatch.setenv("VOICE_STT_BACKEND", "whisper")
    monkeypatch.delenv("VOICE_STT_WHISPER_MODEL_PATH", raising=False)
    service = AudioInputService()
    assert not service.available


def test_audio_input_whisper_rejects_remote_model_path(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_STT", "true")
    monkeypatch.setenv("VOICE_STT_BACKEND", "whisper")
    monkeypatch.setenv("VOICE_STT_WHISPER_MODEL_PATH", "hf://openai/whisper-large-v3")
    service = AudioInputService()
    assert not service.available


def test_audio_input_unsupported_backend_is_disabled(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_STT", "true")
    monkeypatch.setenv("VOICE_STT_BACKEND", "parakeet")
    service = AudioInputService()
    assert not service.available


def test_audio_output_can_be_disabled(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_TTS", "false")
    service = AudioOutputService()
    assert not service.available


@pytest.mark.asyncio
async def test_audio_output_speak_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_TTS", "false")
    monkeypatch.setenv("VOICE_SIMULATE_DELAY", "false")
    service = AudioOutputService()
    await service.speak("Test message")


def test_audio_output_pocket_disabled_without_config(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_TTS", "true")
    monkeypatch.setenv("VOICE_TTS_BACKEND", "pocket")
    monkeypatch.delenv("VOICE_POCKET_CONFIG_PATH", raising=False)
    monkeypatch.delenv("VOICE_POCKET_AUDIO_PROMPT_PATH", raising=False)
    service = AudioOutputService()
    assert not service.available


def test_audio_output_pocket_rejects_remote_sources(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_TTS", "true")
    monkeypatch.setenv("VOICE_TTS_BACKEND", "pocket")
    monkeypatch.setenv("VOICE_POCKET_CONFIG_PATH", "hf://kyutai/pocket-tts/config.yaml")
    monkeypatch.setenv("VOICE_POCKET_AUDIO_PROMPT_PATH", "hf://voices/alba.safetensors")
    service = AudioOutputService()
    assert not service.available


def test_audio_output_unsupported_backend_is_disabled(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_TTS", "true")
    monkeypatch.setenv("VOICE_TTS_BACKEND", "legacy_backend")
    service = AudioOutputService()
    assert not service.available
