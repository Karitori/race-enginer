import pytest

from services.audio_input_service import AudioInputService
from services.audio_output_service import AudioOutputService, _prepare_tts_text


def test_audio_input_disabled_by_default(monkeypatch):
    monkeypatch.delenv("VOICE_ENABLE_STT", raising=False)
    service = AudioInputService()
    assert not service.available


def test_audio_input_whisper_disabled_without_turbo_model(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_STT", "true")
    monkeypatch.setenv("VOICE_STT_BACKEND", "whisper")
    monkeypatch.setenv("VOICE_STT_WHISPER_MODEL", "")
    service = AudioInputService()
    assert not service.available


def test_audio_input_whisper_rejects_remote_model_source(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_STT", "true")
    monkeypatch.setenv("VOICE_STT_BACKEND", "whisper")
    monkeypatch.setenv("VOICE_STT_WHISPER_MODEL", "hf://openai/whisper-large-v3-turbo")
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


def test_audio_output_kokoro_disabled_without_model_files(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_TTS", "true")
    monkeypatch.setenv("VOICE_TTS_BACKEND", "kokoro")
    monkeypatch.delenv("VOICE_KOKORO_MODEL_PATH", raising=False)
    monkeypatch.delenv("VOICE_KOKORO_VOICES_PATH", raising=False)
    service = AudioOutputService()
    assert not service.available


def test_audio_output_kokoro_rejects_remote_sources(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_TTS", "true")
    monkeypatch.setenv("VOICE_TTS_BACKEND", "kokoro")
    monkeypatch.setenv("VOICE_KOKORO_MODEL_PATH", "hf://hexgrad/kokoro/model.onnx")
    monkeypatch.setenv("VOICE_KOKORO_VOICES_PATH", "hf://hexgrad/kokoro/voices-v1.0.bin")
    service = AudioOutputService()
    assert not service.available


def test_audio_output_unsupported_backend_is_disabled(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_TTS", "true")
    monkeypatch.setenv("VOICE_TTS_BACKEND", "legacy_backend")
    service = AudioOutputService()
    assert not service.available


def test_prepare_tts_text_strips_markdown_and_noise():
    raw = "## Strategy\nUse **ERS** now. [note] ~~~"
    prepared = _prepare_tts_text(raw, max_chars=220)
    assert "##" not in prepared
    assert "**" not in prepared
    assert "[" not in prepared
    assert "]" not in prepared
    assert "ERS" in prepared


def test_prepare_tts_text_limits_length():
    raw = "A " * 300
    prepared = _prepare_tts_text(raw, max_chars=100)
    assert len(prepared) <= 101
