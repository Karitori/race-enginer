import pytest

from services.audio_input_service import AudioInputService
from services.audio_output_service import (
    AudioOutputService,
    _parse_piper_extra_args,
    _select_pyttsx3_voice_id,
)


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


def test_audio_output_piper_disabled_without_model(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLE_TTS", "true")
    monkeypatch.setenv("VOICE_TTS_BACKEND", "piper")
    monkeypatch.delenv("VOICE_PIPER_MODEL_PATH", raising=False)
    service = AudioOutputService()
    assert not service.available


def test_audio_output_piper_disabled_when_exe_missing(monkeypatch, tmp_path):
    model_file = tmp_path / "voice.onnx"
    model_file.write_text("x", encoding="utf-8")
    monkeypatch.setenv("VOICE_ENABLE_TTS", "true")
    monkeypatch.setenv("VOICE_TTS_BACKEND", "piper")
    monkeypatch.setenv("VOICE_PIPER_MODEL_PATH", str(model_file))
    monkeypatch.setattr("services.audio_output_service.shutil.which", lambda _exe: None)
    service = AudioOutputService()
    assert not service.available


def test_audio_output_piper_enabled_when_exe_and_model_exist(monkeypatch, tmp_path):
    model_file = tmp_path / "voice.onnx"
    model_file.write_text("x", encoding="utf-8")
    monkeypatch.setenv("VOICE_ENABLE_TTS", "true")
    monkeypatch.setenv("VOICE_TTS_BACKEND", "piper")
    monkeypatch.setenv("VOICE_PIPER_MODEL_PATH", str(model_file))
    monkeypatch.setattr(
        "services.audio_output_service.shutil.which", lambda _exe: "C:\\piper.exe"
    )
    service = AudioOutputService()
    assert service.available


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


def test_parse_piper_extra_args():
    parsed = _parse_piper_extra_args("--length_scale 0.95 --noise_scale 0.667")
    assert parsed == ["--length_scale", "0.95", "--noise_scale", "0.667"]


class _FakeVoice:
    def __init__(self, voice_id: str, name: str):
        self.id = voice_id
        self.name = name
        self.languages = ["en-US"]


def test_select_pyttsx3_voice_id_prefers_hint():
    voices = [_FakeVoice("v1", "Microsoft David"), _FakeVoice("v2", "Microsoft Jenny")]
    selected = _select_pyttsx3_voice_id(voices, hint="jenny")
    assert selected == "v2"
