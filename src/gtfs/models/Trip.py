from pydantic import BaseModel, ConfigDict


class Trip(BaseModel):
    """GTFS trip."""
    model_config = ConfigDict(frozen=True)

    trip_id: str
    route_id: str
    service_id: str
    direction_id: int = 0
