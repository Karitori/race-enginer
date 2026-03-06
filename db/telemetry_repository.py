from db.contracts import TelemetryRepository
from db.telemetry_store import TelemetryStore


class DuckDBTelemetryRepository(TelemetryRepository):
    """DuckDB repository adapter around the TelemetryStore implementation."""

    def __init__(self, db_path: str = "live_session.duckdb"):
        self._store = TelemetryStore(db_path)

    @property
    def store(self) -> TelemetryStore:
        return self._store

    def query(self, sql: str):
        return self._store.query(sql)

    def close(self) -> None:
        self._store.close()



