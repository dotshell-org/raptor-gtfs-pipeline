"""Binary serialization for RAPTOR data structures."""

import logging
import struct
from pathlib import Path
from typing import BinaryIO

from raptor_pipeline.gtfs.models import NetworkIndex, RouteData, StopData
from raptor_pipeline.transform.compression import encode_times

logger = logging.getLogger(__name__)


class BinaryWriter:
    """Base class for binary writers."""

    def __init__(self, file: BinaryIO) -> None:
        """Initialize writer with file handle."""
        self.file = file
        self.offset = 0

    def write_bytes(self, data: bytes) -> None:
        """Write raw bytes and track offset."""
        self.file.write(data)
        self.offset += len(data)

    def write_uint16(self, value: int) -> None:
        """Write uint16 in little-endian."""
        self.write_bytes(struct.pack("<H", value))

    def write_uint32(self, value: int) -> None:
        """Write uint32 in little-endian."""
        self.write_bytes(struct.pack("<I", value))

    def write_uint64(self, value: int) -> None:
        """Write uint64 in little-endian."""
        self.write_bytes(struct.pack("<Q", value))

    def write_int32(self, value: int) -> None:
        """Write int32 in little-endian."""
        self.write_bytes(struct.pack("<i", value))

    def write_float64(self, value: float) -> None:
        """Write float64 in little-endian."""
        self.write_bytes(struct.pack("<d", value))

    def write_string(self, value: str) -> None:
        """Write length-prefixed UTF-8 string."""
        encoded = value.encode("utf-8")
        self.write_uint16(len(encoded))
        self.write_bytes(encoded)


class RoutesWriter(BinaryWriter):
    """Writer for routes.bin."""

    MAGIC = b"RRTS"

    def write_header(self, schema_version: int, route_count: int) -> None:
        """Write routes.bin header."""
        self.write_bytes(self.MAGIC)
        self.write_uint16(schema_version)
        self.write_uint32(route_count)

    def write_route(self, route: RouteData, compression: bool = True) -> int:
        """Write a single route and return its offset."""
        route_offset = self.offset

        self.write_uint32(route.route_id_internal)
        self.write_string(route.route_name)
        self.write_uint32(len(route.stop_ids))
        self.write_uint32(len(route.trips))

        # Write stop IDs
        for stop_id in route.stop_ids:
            self.write_uint32(stop_id)

        # Write trips
        for trip in route.trips:
            self.write_uint32(trip.trip_id_internal)

            # Encode times
            times = [t for t in trip.arrival_times if t != float("inf")]
            if compression:
                encoded_times = encode_times(times)
            else:
                encoded_times = times

            # Write encoded times
            for time in encoded_times:
                self.write_int32(time)

        return route_offset


class StopsWriter(BinaryWriter):
    """Writer for stops.bin."""

    MAGIC = b"RSTS"

    def write_header(self, schema_version: int, stop_count: int) -> None:
        """Write stops.bin header."""
        self.write_bytes(self.MAGIC)
        self.write_uint16(schema_version)
        self.write_uint32(stop_count)

    def write_stop(self, stop: StopData) -> int:
        """Write a single stop and return its offset."""
        stop_offset = self.offset

        self.write_uint32(stop.stop_id_internal)
        self.write_string(stop.name)
        self.write_float64(stop.lat)
        self.write_float64(stop.lon)

        # Write route references
        self.write_uint32(len(stop.route_ids))
        for route_id in stop.route_ids:
            self.write_uint32(route_id)

        # Write transfers
        self.write_uint32(len(stop.transfers))
        for target_stop, walk_time in stop.transfers:
            self.write_uint32(target_stop)
            self.write_int32(walk_time)

        return stop_offset


class IndexWriter(BinaryWriter):
    """Writer for index.bin."""

    MAGIC = b"RIDX"

    def write_header(self, schema_version: int) -> None:
        """Write index.bin header."""
        self.write_bytes(self.MAGIC)
        self.write_uint16(schema_version)

    def write_index(self, index: NetworkIndex) -> None:
        """Write complete index data."""
        # Write stop_to_routes
        self.write_uint32(len(index.stop_to_routes))
        for stop_id in sorted(index.stop_to_routes.keys()):
            route_ids = index.stop_to_routes[stop_id]
            self.write_uint32(stop_id)
            self.write_uint32(len(route_ids))
            for route_id in route_ids:
                self.write_uint32(route_id)

        # Write route_offsets
        self.write_uint32(len(index.route_offsets))
        for route_id in sorted(index.route_offsets.keys()):
            offset = index.route_offsets[route_id]
            self.write_uint32(route_id)
            self.write_uint64(offset)

        # Write stop_offsets
        self.write_uint32(len(index.stop_offsets))
        for stop_id in sorted(index.stop_offsets.keys()):
            offset = index.stop_offsets[stop_id]
            self.write_uint32(stop_id)
            self.write_uint64(offset)


def write_binary_files(
    output_path: Path,
    routes: list[RouteData],
    stops: list[StopData],
    index: NetworkIndex,
    schema_version: int,
    compression: bool = True,
) -> dict[str, str]:
    """Write all binary files and return filenames."""
    logger.info(f"Writing binary files to {output_path}")

    output_path.mkdir(parents=True, exist_ok=True)

    files_written = {}

    # Write routes.bin
    routes_path = output_path / "routes.bin"
    with open(routes_path, "wb") as f:
        writer = RoutesWriter(f)
        writer.write_header(schema_version, len(routes))

        for route in routes:
            offset = writer.write_route(route, compression=compression)
            index.route_offsets[route.route_id_internal] = offset

    files_written["routes.bin"] = str(routes_path)
    logger.info(f"Wrote {routes_path}")

    # Write stops.bin
    stops_path = output_path / "stops.bin"
    with open(stops_path, "wb") as f:
        stops_writer = StopsWriter(f)
        stops_writer.write_header(schema_version, len(stops))

        for stop in stops:
            offset = stops_writer.write_stop(stop)
            index.stop_offsets[stop.stop_id_internal] = offset

    files_written["stops.bin"] = str(stops_path)
    logger.info(f"Wrote {stops_path}")

    # Write index.bin
    index_path = output_path / "index.bin"
    with open(index_path, "wb") as f:
        index_writer = IndexWriter(f)
        index_writer.write_header(schema_version)
        index_writer.write_index(index)

    files_written["index.bin"] = str(index_path)
    logger.info(f"Wrote {index_path}")

    return files_written


class BinaryReader:
    """Base class for binary readers."""

    def __init__(self, file: BinaryIO) -> None:
        """Initialize reader with file handle."""
        self.file = file

    def read_bytes(self, n: int) -> bytes:
        """Read n bytes."""
        data = self.file.read(n)
        if len(data) != n:
            raise ValueError(f"Expected {n} bytes, got {len(data)}")
        return data

    def read_uint16(self) -> int:
        """Read uint16 in little-endian."""
        result: int = struct.unpack("<H", self.read_bytes(2))[0]
        return result

    def read_uint32(self) -> int:
        """Read uint32 in little-endian."""
        result: int = struct.unpack("<I", self.read_bytes(4))[0]
        return result

    def read_uint64(self) -> int:
        """Read uint64 in little-endian."""
        result: int = struct.unpack("<Q", self.read_bytes(8))[0]
        return result

    def read_int32(self) -> int:
        """Read int32 in little-endian."""
        result: int = struct.unpack("<i", self.read_bytes(4))[0]
        return result

    def read_float64(self) -> float:
        """Read float64 in little-endian."""
        result: float = struct.unpack("<d", self.read_bytes(8))[0]
        return result

    def read_string(self) -> str:
        """Read length-prefixed UTF-8 string."""
        length = self.read_uint16()
        return self.read_bytes(length).decode("utf-8")


def validate_binary_files(output_path: Path) -> dict[str, int]:
    """Validate binary files can be read and return counts."""
    logger.info(f"Validating binary files in {output_path}")

    stats = {}

    # Validate routes.bin
    routes_path = output_path / "routes.bin"
    with open(routes_path, "rb") as f:
        reader = BinaryReader(f)
        magic = reader.read_bytes(4)
        if magic != b"RRTS":
            raise ValueError(f"Invalid routes.bin magic: {magic!r}")
        schema_version = reader.read_uint16()
        route_count = reader.read_uint32()
        stats["routes"] = route_count
        logger.info(f"routes.bin: schema={schema_version}, routes={route_count}")

    # Validate stops.bin
    stops_path = output_path / "stops.bin"
    with open(stops_path, "rb") as f:
        reader = BinaryReader(f)
        magic = reader.read_bytes(4)
        if magic != b"RSTS":
            raise ValueError(f"Invalid stops.bin magic: {magic!r}")
        schema_version = reader.read_uint16()
        stop_count = reader.read_uint32()
        stats["stops"] = stop_count
        logger.info(f"stops.bin: schema={schema_version}, stops={stop_count}")

    # Validate index.bin
    index_path = output_path / "index.bin"
    with open(index_path, "rb") as f:
        reader = BinaryReader(f)
        magic = reader.read_bytes(4)
        if magic != b"RIDX":
            raise ValueError(f"Invalid index.bin magic: {magic!r}")
        schema_version = reader.read_uint16()
        logger.info(f"index.bin: schema={schema_version}")

    logger.info("Binary file validation passed")
    return stats
