import asyncio

import pytest

from services.audio_input_service import AudioInputService
from services.audio_output_service import AudioOutputService, _parse_style_hint, _prepare_tts_text


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


def test_audio_input_control_toggle_default_off(monkeypatch):
    monkeypatch.setenv("VOICE_STT_BACKEND", "whisper")
    monkeypatch.setenv("VOICE_STT_CONTROL_MODE", "toggle")
    monkeypatch.setenv("VOICE_STT_TOGGLE_DEFAULT_ON", "false")
    service = AudioInputService()
    status = service.get_control_status()
    assert status["control_mode"] == "toggle"
    assert status["capture_gate_open"] is False
    assert "mic_index" in status
    assert "mic_name" in status


def test_audio_input_control_toggle_action(monkeypatch):
    monkeypatch.setenv("VOICE_STT_BACKEND", "whisper")
    monkeypatch.setenv("VOICE_STT_CONTROL_MODE", "toggle")
    monkeypatch.setenv("VOICE_STT_TOGGLE_DEFAULT_ON", "false")
    service = AudioInputService()
    status = service.apply_control_action(action="toggle")
    assert status["capture_gate_open"] is True


def test_audio_input_control_ptt_actions(monkeypatch):
    monkeypatch.setenv("VOICE_STT_BACKEND", "whisper")
    monkeypatch.setenv("VOICE_STT_CONTROL_MODE", "ptt")
    service = AudioInputService()
    status_down = service.apply_control_action(action="ptt_down")
    assert status_down["capture_gate_open"] is True
    status_up = service.apply_control_action(action="ptt_up")
    assert status_up["capture_gate_open"] is False


def test_audio_input_control_set_mic(monkeypatch):
    monkeypatch.setenv("VOICE_STT_BACKEND", "whisper")
    service = AudioInputService()
    status = service.apply_control_action(action="set_mic", mic_index=2)
    assert status["mic_index"] == 2


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


def test_parse_style_hint_defaults_for_unknown():
    assert _parse_style_hint("something", fallback="info") == "info"
    assert _parse_style_hint("warning", fallback="info") == "warning"


def test_kokoro_profile_uses_warning_speed_for_critical(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_TTS", "false")
    service = AudioOutputService()
    _voice, speed = service._resolve_kokoro_profile(style_hint="info", priority=5)
    assert speed == service._kokoro_speed_warning


def test_apply_expressive_format_adds_urgency(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_TTS", "false")
    service = AudioOutputService()
    formatted = service._apply_expressive_format("Box this lap", "warning", 4)
    assert formatted.endswith("!")


@pytest.mark.asyncio
async def test_audio_output_simulated_speech_interrupt(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_TTS", "false")
    monkeypatch.setenv("VOICE_SIMULATE_DELAY", "true")
    service = AudioOutputService()

    speaking_task = asyncio.create_task(service.speak("Push now " * 200))
    await asyncio.sleep(0.05)
    interrupted = service.interrupt_playback()
    await asyncio.wait_for(speaking_task, timeout=0.5)

    assert interrupted is True
