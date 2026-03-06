import asyncio

import pytest

from services.telemetry_mode_service import TelemetryModeService


class FakeMockParser:
    def __init__(self):
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True
        while not self.stopped:
            await asyncio.sleep(0.01)

    def stop(self):
        self.stopped = True


@pytest.mark.asyncio
async def test_telemetry_mode_defaults_to_real(monkeypatch):
    monkeypatch.delenv("TELEMETRY_MODE", raising=False)
    service = TelemetryModeService()
    assert service.mode == "real"


@pytest.mark.asyncio
async def test_switch_to_mock_starts_mock_parser(monkeypatch):
    monkeypatch.setattr("services.telemetry_mode_service.BaseTelemetryParser", FakeMockParser)
    service = TelemetryModeService()

    await service.switch_mode("mock")
    await asyncio.sleep(0.02)

    status = service.get_status()
    assert status["mode"] == "mock"
    assert status["status"] == "running"

    await service._stop_active_parser()


@pytest.mark.asyncio
async def test_real_mode_missing_parser_sets_error(monkeypatch):
    monkeypatch.setenv("TELEMETRY_MODE", "real")
    monkeypatch.setenv("TELEMETRY_FALLBACK_TO_MOCK", "false")
    monkeypatch.setattr("services.telemetry_mode_service.is_ctypes_parser_available", lambda: False)
    service = TelemetryModeService()

    await service.switch_mode("real")
    status = service.get_status()
    assert status["mode"] == "real"
    assert status["status"] == "error"
    assert "Missing F1 25 parser definitions" in status["error"]


@pytest.mark.asyncio
async def test_real_mode_missing_parser_falls_back_to_mock(monkeypatch):
    monkeypatch.setenv("TELEMETRY_MODE", "real")
    monkeypatch.setenv("TELEMETRY_FALLBACK_TO_MOCK", "true")
    monkeypatch.setattr("services.telemetry_mode_service.is_ctypes_parser_available", lambda: False)
    monkeypatch.setattr("services.telemetry_mode_service.BaseTelemetryParser", FakeMockParser)
    service = TelemetryModeService()

    await service.switch_mode("real")
    await asyncio.sleep(0.02)

    status = service.get_status()
    assert status["mode"] == "mock"
    assert status["status"] == "running"

    await service._stop_active_parser()

