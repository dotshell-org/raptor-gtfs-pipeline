from pydantic import BaseModel, ConfigDict


class Calendar(BaseModel):
    """GTFS calendar entry."""
    model_config = ConfigDict(frozen=True)

    service_id: str
    monday: bool
    tuesday: bool
    wednesday: bool
    thursday: bool
    friday: bool
    saturday: bool
    sunday: bool
    start_date: str  # YYYYMMDD
    end_date: str  # YYYYMMDD
