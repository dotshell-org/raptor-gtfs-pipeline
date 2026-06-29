from pydantic import BaseModel, ConfigDict


class Agency(BaseModel):
    """GTFS agency."""
    model_config = ConfigDict(frozen=True)

    agency_id: str
    agency_name: str
    agency_timezone: str
