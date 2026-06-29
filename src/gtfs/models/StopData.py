from pydantic import BaseModel, Field


class StopData(BaseModel):
    """Internal stop representation with route references and transfers."""

    stop_id_internal: int
    stop_id_gtfs: str
    name: str
    lat: float
    lon: float
    route_ids: list[int] = Field(default_factory=list)
    transfers: list[tuple[int, int]] = Field(default_factory=list)  # (target_stop_id, walk_time)
