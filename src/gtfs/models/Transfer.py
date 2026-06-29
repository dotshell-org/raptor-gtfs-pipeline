from pydantic import BaseModel, ConfigDict


class Transfer(BaseModel):
    """GTFS transfer between stops."""
    model_config = ConfigDict(frozen=True)

    from_stop_id: str
    to_stop_id: str
    min_transfer_time: int  # seconds
