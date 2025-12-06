"""Tests for JSON output."""

import json
from pathlib import Path

from raptor_pipeline.gtfs.reader import GTFSReader
from raptor_pipeline.optimization.indexing import build_network_index
from raptor_pipeline.output.json import write_json_files
from raptor_pipeline.transform.routes import build_routes
from raptor_pipeline.transform.stops import build_stops
from raptor_pipeline.transform.transfers import build_transfers
from raptor_pipeline.transform.trips import build_and_sort_trips


def test_write_json_files(gtfs_minimal: Path, tmp_output: Path) -> None:
    """Test writing JSON debug files."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    routes = build_routes(reader)
    build_and_sort_trips(reader, routes)
    stops = build_stops(reader, routes)
    build_transfers(reader, stops)
    index = build_network_index(routes, stops)

    files = write_json_files(tmp_output, routes, stops, index)

    assert "routes.json" in files
    assert "stops.json" in files
    assert "index.json" in files


def test_json_routes_structure(gtfs_minimal: Path, tmp_output: Path) -> None:
    """Test routes.json has correct structure."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    routes = build_routes(reader)
    build_and_sort_trips(reader, routes)
    stops = build_stops(reader, routes)
    build_transfers(reader, stops)
    index = build_network_index(routes, stops)

    write_json_files(tmp_output, routes, stops, index)

    with open(tmp_output / "routes.json", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) == 1
    route = data[0]

    assert "route_id_internal" in route
    assert "route_id_gtfs" in route
    assert "stop_ids" in route
    assert "trips" in route


def test_json_stops_structure(gtfs_minimal: Path, tmp_output: Path) -> None:
    """Test stops.json has correct structure."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    routes = build_routes(reader)
    build_and_sort_trips(reader, routes)
    stops = build_stops(reader, routes)
    build_transfers(reader, stops)
    index = build_network_index(routes, stops)

    write_json_files(tmp_output, routes, stops, index)

    with open(tmp_output / "stops.json", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) == 3

    for stop in data:
        assert "stop_id_internal" in stop
        assert "stop_id_gtfs" in stop
        assert "name" in stop
        assert "lat" in stop
        assert "lon" in stop
        assert "route_ids" in stop
        assert "transfers" in stop


def test_json_stable_sort(gtfs_minimal: Path, tmp_output: Path) -> None:
    """Test JSON output is deterministic with sorted keys."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    routes = build_routes(reader)
    build_and_sort_trips(reader, routes)
    stops = build_stops(reader, routes)
    build_transfers(reader, stops)
    index = build_network_index(routes, stops)

    # Write twice
    write_json_files(tmp_output, routes, stops, index)
    with open(tmp_output / "routes.json", encoding="utf-8") as f:
        content1 = f.read()

    write_json_files(tmp_output, routes, stops, index)
    with open(tmp_output / "routes.json", encoding="utf-8") as f:
        content2 = f.read()

    # Should be identical
    assert content1 == content2
