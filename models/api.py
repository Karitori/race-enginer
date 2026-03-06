from pydantic import BaseModel


class DriverQueryPayload(BaseModel):
    query: str


class SQLQueryPayload(BaseModel):
    sql: str


class TelemetryModePayload(BaseModel):
    mode: str  # "mock" or "real"
    host: str = "0.0.0.0"
    port: int = 20777
