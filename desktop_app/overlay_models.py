from pydantic import BaseModel, Field


class OverlaySettings(BaseModel):
    server_host: str = "127.0.0.1"
    server_port: int = Field(8000, ge=1, le=65535)
    width: int = Field(460, ge=320, le=1400)
    height: int = Field(240, ge=180, le=1000)
    x: int = 20
    y: int = 20
    opacity: float = Field(0.8, ge=0.35, le=1.0)
    font_size: int = Field(11, ge=9, le=24)
    always_on_top: bool = True
    show_only_when_connected: bool = False
    default_talk_level: int = Field(5, ge=1, le=10)


class OverlayState(BaseModel):
    speed: int = 0
    gear: str = "N"
    lap: int = 1
    sector: int = 1
    telemetry_mode: str = "real"
    telemetry_status: str = "starting"
    latest_engineer_message: str = "Waiting for race engineer..."
    latest_strategy_message: str = "Waiting for strategy agent..."
