"""Data models for GTFS and internal representations."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Stop:
    """GTFS stop with coordinates."""

    stop_id: str
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Route:
    """GTFS route."""

    route_id: str
    route_short_name: str
    route_long_name: str
    route_type: int


@dataclass(frozen=True)
class Trip:
    """GTFS trip."""

    trip_id: str
    route_id: str
    service_id: str
    direction_id: int = 0


@dataclass(frozen=True)
class StopTime:
    """GTFS stop time."""

    trip_id: str
    stop_id: str
    arrival_time: int  # seconds since midnight
    departure_time: int  # seconds since midnight
    stop_sequence: int


@dataclass(frozen=True)
class Transfer:
    """GTFS transfer between stops."""

    from_stop_id: str
    to_stop_id: str
    min_transfer_time: int  # seconds


@dataclass(frozen=True)
class Agency:
    """GTFS agency."""

    agency_id: str
    agency_name: str
    agency_timezone: str


@dataclass
class StopData:
    """Internal stop representation with route references and transfers."""

    stop_id_internal: int
    stop_id_gtfs: str
    name: str
    lat: float
    lon: float
    route_ids: list[int] = field(default_factory=list)
    transfers: list[tuple[int, int]] = field(default_factory=list)  # (target_stop_id, walk_time)


@dataclass
class TripData:
    """Internal trip representation with aligned arrival times."""

    trip_id_internal: int
    trip_id_gtfs: str
    arrival_times: list[int]  # aligned to canonical stop sequence, +inf for missing
    is_partial: bool = False


@dataclass
class RouteData:
    """Internal route representation with canonical stop sequence and trips."""

    route_id_internal: int
    route_id_gtfs: str
    route_name: str  # route_short_name or route_long_name
    stop_ids: list[int]  # canonical stop sequence
    trips: list[TripData] = field(default_factory=list)


@dataclass
class NetworkIndex:
    """Index structures for fast lookups."""

    stop_to_routes: dict[int, list[int]] = field(default_factory=dict)
    route_offsets: dict[int, int] = field(default_factory=dict)  # route_id -> offset in routes.bin
    stop_offsets: dict[int, int] = field(default_factory=dict)  # stop_id -> offset in stops.bin


@dataclass
class Manifest:
    """Build manifest with metadata and checksums."""

    schema_version: int
    tool_version: str
    created_at_iso: str
    inputs: dict[str, Any]
    outputs: dict[str, str]  # filename -> sha256
    stats: dict[str, int]
    build: dict[str, str]


@dataclass
class ValidationReport:
    """Report from validation process."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


@dataclass
class ConvertConfig:
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
