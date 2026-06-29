from pydantic import BaseModel, ConfigDict


class CalendarDate(BaseModel):
    """GTFS calendar_dates exception."""
    model_config = ConfigDict(frozen=True)

    service_id: str
    date: str  # YYYYMMDD
    exception_type: int  # 1=added, 2=removed
