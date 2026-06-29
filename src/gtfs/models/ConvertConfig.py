from pydantic import BaseModel


class ConvertConfig(BaseModel):
    """Configuration for conversion process."""

    input_path: str
    output_path: str
    format: str = "binary"  # binary, json, both
    compression: bool = True
    debug_json: bool = False
    gen_transfers: bool = False
    allow_partial_trips: bool = False
    speed_walk: float = 1.33  # m/s
    transfer_cutoff: int = 500  # meters
    jobs: int = 1
    split_by_periods: bool = False  # Generate separate folders per service period
