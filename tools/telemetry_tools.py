from __future__ import annotations

from typing import Any, Protocol

from langchain_core.tools import tool


class TelemetryToolProvider(Protocol):
    def get_gap_snapshot(self) -> dict[str, Any]:
        ...

    def get_car_state_snapshot(self) -> dict[str, Any]:
        ...

    def get_health_snapshot(self) -> dict[str, Any]:
        ...

    def get_full_telemetry_snapshot(self) -> dict[str, Any]:
        ...


_provider: TelemetryToolProvider | None = None


def set_telemetry_tool_provider(provider: TelemetryToolProvider) -> None:
    global _provider
    _provider = provider


def _require_provider() -> TelemetryToolProvider:
    if _provider is None:
        raise RuntimeError("telemetry tool provider is not configured")
    return _provider


@tool("telemetry_gap")
def telemetry_gap() -> dict[str, Any]:
    """Return current lap, position, and gap values for the player car."""
    return _require_provider().get_gap_snapshot()


@tool("telemetry_car_state")
def telemetry_car_state() -> dict[str, Any]:
    """Return fuel, ERS, tyre, and DRS state for the player car."""
    return _require_provider().get_car_state_snapshot()


@tool("telemetry_health")
def telemetry_health() -> dict[str, Any]:
    """Return damage and temperature health indicators for the player car."""
    return _require_provider().get_health_snapshot()


@tool("telemetry_full_snapshot")
def telemetry_full_snapshot() -> dict[str, Any]:
    """Return a full multi-packet telemetry snapshot for the player car and session."""
    return _require_provider().get_full_telemetry_snapshot()


def get_engineer_tools() -> list[Any]:
    return [
        telemetry_gap,
        telemetry_car_state,
        telemetry_health,
        telemetry_full_snapshot,
    ]
