"""Protobuf output (stub implementation)."""

import logging
from pathlib import Path

from raptor_pipeline.gtfs.models import NetworkIndex, RouteData, StopData

logger = logging.getLogger(__name__)


# Stub .proto specification (for documentation)
PROTO_SPEC = """
syntax = "proto3";

package raptor;

message StopData {
  uint32 stop_id_internal = 1;
  string stop_id_gtfs = 2;
  string name = 3;
  double lat = 4;
  double lon = 5;
  repeated uint32 route_ids = 6;
  repeated Transfer transfers = 7;
}

message Transfer {
  uint32 target_stop_id = 1;
  int32 walk_time = 2;
}

message TripData {
  uint32 trip_id_internal = 1;
  string trip_id_gtfs = 2;
  repeated int32 arrival_times = 3;
  bool is_partial = 4;
}

message RouteData {
  uint32 route_id_internal = 1;
  string route_id_gtfs = 2;
  repeated uint32 stop_ids = 3;
  repeated TripData trips = 4;
}

message NetworkData {
  repeated RouteData routes = 1;
  repeated StopData stops = 2;
  NetworkIndex index = 3;
}

message NetworkIndex {
  map<uint32, RouteList> stop_to_routes = 1;
  map<uint32, uint64> route_offsets = 2;
  map<uint32, uint64> stop_offsets = 3;
}

message RouteList {
  repeated uint32 route_ids = 1;
}
"""


def write_protobuf_spec(output_path: Path) -> None:
    """Write .proto specification file."""
    proto_path = output_path / "raptor.proto"
    with open(proto_path, "w", encoding="utf-8") as f:
        f.write(PROTO_SPEC)
    logger.info(f"Wrote protobuf spec to {proto_path}")


def write_protobuf_files(
    output_path: Path,
    routes: list[RouteData],
    stops: list[StopData],
    index: NetworkIndex,
) -> dict[str, str]:
    """
    Write protobuf files (stub - not implemented).

    To implement:
    1. Generate Python code from .proto using protoc
    2. Serialize data structures using generated classes
    3. Write to .pb files
    """
    logger.warning("Protobuf writer is a stub - not generating .pb files")

    # Write spec for reference
    write_protobuf_spec(output_path)

    return {"raptor.proto": str(output_path / "raptor.proto")}
