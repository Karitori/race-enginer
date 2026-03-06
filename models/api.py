from pydantic import BaseModel


class DriverQueryPayload(BaseModel):
    query: str


class SQLQueryPayload(BaseModel):
    sql: str


class TelemetryModePayload(BaseModel):
    mode: str  # "mock" or "real"
    host: str = "0.0.0.0"
    port: int = 20777


class STTControlPayload(BaseModel):
    action: str
    enabled: bool | None = None
    mode: str | None = None
