from pydantic import BaseModel, ConfigDict


class Route(BaseModel):
    """GTFS route."""
    model_config = ConfigDict(frozen=True)

    route_id: str
    route_short_name: str
    route_long_name: str
    route_type: int
