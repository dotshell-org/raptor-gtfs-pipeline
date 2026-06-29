from pydantic import BaseModel, ConfigDict


class Stop(BaseModel):
    """GTFS stop with coordinates."""
    model_config = ConfigDict(frozen=True)

    stop_id: str
    name: str
    lat: float
    lon: float
