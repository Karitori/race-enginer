from typing import Protocol, Any


class TelemetryRepository(Protocol):
    """Persistence/query boundary for telemetry and analytics data."""

    def query(self, sql: str) -> list[tuple[Any, ...]]:
        ...

    def close(self) -> None:
        ...
