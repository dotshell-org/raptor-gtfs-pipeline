from pydantic import BaseModel


class TripData(BaseModel):
    """Internal trip representation with aligned arrival times."""

    trip_id_internal: int
    trip_id_gtfs: str
    arrival_times: list[float]  # aligned to canonical stop sequence, +inf for missing
    is_partial: bool = False
