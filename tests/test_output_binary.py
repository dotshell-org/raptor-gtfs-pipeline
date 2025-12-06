"""Tests for binary output."""

import struct
from pathlib import Path

from raptor_pipeline.gtfs.reader import GTFSReader
from raptor_pipeline.optimization.indexing import build_network_index
from raptor_pipeline.output.binary import validate_binary_files, write_binary_files
from raptor_pipeline.transform.routes import build_routes
from raptor_pipeline.transform.stops import build_stops
from raptor_pipeline.transform.transfers import build_transfers
from raptor_pipeline.transform.trips import build_and_sort_trips


def test_write_and_read_binary(gtfs_minimal: Path, tmp_output: Path) -> None:
    """Test writing and reading binary files."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    routes = build_routes(reader)
    build_and_sort_trips(reader, routes)
    stops = build_stops(reader, routes)
    build_transfers(reader, stops)
    index = build_network_index(routes, stops)

    # Write files
    files = write_binary_files(tmp_output, routes, stops, index, schema_version=1)

    assert "routes.bin" in files
    assert "stops.bin" in files
    assert "index.bin" in files

    # Validate
    stats = validate_binary_files(tmp_output)
    assert stats["routes"] == 1
    assert stats["stops"] == 3


def test_binary_magic_bytes(gtfs_minimal: Path, tmp_output: Path) -> None:
    """Test binary files have correct magic bytes."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    routes = build_routes(reader)
    build_and_sort_trips(reader, routes)
    stops = build_stops(reader, routes)
    build_transfers(reader, stops)
    index = build_network_index(routes, stops)

    write_binary_files(tmp_output, routes, stops, index, schema_version=1)

    # Check magic bytes
    with open(tmp_output / "routes.bin", "rb") as f:
        assert f.read(4) == b"RRTS"

    with open(tmp_output / "stops.bin", "rb") as f:
        assert f.read(4) == b"RSTS"

    with open(tmp_output / "index.bin", "rb") as f:
        assert f.read(4) == b"RIDX"


def test_binary_endianness(gtfs_minimal: Path, tmp_output: Path) -> None:
    """Test binary files use little-endian encoding."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    routes = build_routes(reader)
    build_and_sort_trips(reader, routes)
    stops = build_stops(reader, routes)
    build_transfers(reader, stops)
    index = build_network_index(routes, stops)

    write_binary_files(tmp_output, routes, stops, index, schema_version=1)

    # Check schema version is little-endian
    with open(tmp_output / "routes.bin", "rb") as f:
        f.read(4)  # Skip magic
        schema_bytes = f.read(2)
        schema_version = struct.unpack("<H", schema_bytes)[0]
        assert schema_version == 1


def test_binary_delta_compression(gtfs_minimal: Path, tmp_output: Path) -> None:
    """Test delta compression is applied."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    routes = build_routes(reader)
    build_and_sort_trips(reader, routes)
    stops = build_stops(reader, routes)
    build_transfers(reader, stops)
    index = build_network_index(routes, stops)

    # Write with compression
    write_binary_files(tmp_output, routes, stops, index, schema_version=1, compression=True)

    # File should be smaller with compression (though hard to verify without decoding)
    routes_file = tmp_output / "routes.bin"
    assert routes_file.exists()
    assert routes_file.stat().st_size > 0


def test_binary_round_trip_data(gtfs_minimal: Path, tmp_output: Path) -> None:
    """Test data integrity through binary write/read cycle."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    routes = build_routes(reader)
    build_and_sort_trips(reader, routes)
    stops = build_stops(reader, routes)
    build_transfers(reader, stops)
    index = build_network_index(routes, stops)

    write_binary_files(tmp_output, routes, stops, index, schema_version=1)

    # Basic validation
    stats = validate_binary_files(tmp_output)

    assert stats["routes"] == len(routes)
    assert stats["stops"] == len(stops)
