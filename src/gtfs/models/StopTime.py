from pydantic import BaseModel, ConfigDict


class StopTime(BaseModel):
    """GTFS stop time."""
    model_config = ConfigDict(frozen=True)

    trip_id: str
    stop_id: str
    arrival_time: int  # seconds since midnight
    departure_time: int  # seconds since midnight
    stop_sequence: int
