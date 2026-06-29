from pydantic import BaseModel, Field
from src.gtfs.models.TripData import TripData


class RouteData(BaseModel):
    """Internal route representation with canonical stop sequence and trips."""

    route_id_internal: int
    route_id_gtfs: str
    route_name: str  # route_short_name or route_long_name
    stop_ids: list[int]  # canonical stop sequence
    trips: list[TripData] = Field(default_factory=list)
