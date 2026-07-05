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
    gen_traces: bool = False  # Generate line geometry (lines.bin) from shapes.txt
    dry_run: bool = False  # Print the period plan without writing any files
    flat_output: bool = False  # Flat per-period files (routes_<period>.bin) vs subfolders
    write_index: bool = True  # Write index.bin/.json (disable with --no-index)
    pelo: bool = False  # Pelo preset: bare stops_/routes_<period>.bin at the root, nothing else
