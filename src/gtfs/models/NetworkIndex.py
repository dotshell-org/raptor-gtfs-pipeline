from pydantic import BaseModel, Field


class NetworkIndex(BaseModel):
    """Index structures for fast lookups."""

    stop_to_routes: dict[int, list[int]] = Field(default_factory=dict)
    route_offsets: dict[int, int] = Field(default_factory=dict)  # route_id -> offset in routes.bin
    stop_offsets: dict[int, int] = Field(default_factory=dict)  # stop_id -> offset in stops.bin
