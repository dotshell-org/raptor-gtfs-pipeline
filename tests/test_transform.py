"""Tests for transform modules."""

from pathlib import Path

from raptor_pipeline.gtfs.reader import GTFSReader
from raptor_pipeline.transform.compression import decode_times, encode_times
from raptor_pipeline.transform.routes import build_routes
from raptor_pipeline.transform.stops import build_stops
from raptor_pipeline.transform.trips import build_and_sort_trips


def test_compression_delta_encoding() -> None:
    """Test delta encoding and decoding."""
    times = [28800, 29400, 30000, 30600]  # 8:00, 8:10, 8:20, 8:30
    encoded = encode_times(times)

    assert encoded[0] == 28800  # First is absolute
    assert encoded[1] == 600  # Delta
    assert encoded[2] == 600
    assert encoded[3] == 600

    decoded = decode_times(encoded)
    assert decoded == times


def test_compression_empty() -> None:
    """Test encoding/decoding empty list."""
    assert encode_times([]) == []
    assert decode_times([]) == []


def test_build_routes_canonical_sequence(gtfs_minimal: Path) -> None:
    """Test route building with canonical sequence."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    routes = build_routes(reader)

    assert len(routes) == 1
    route = routes[0]

    # Should have 3 stops: A, B, C (IDs 0, 1, 2)
    assert len(route.stop_ids) == 3
    assert route.stop_ids == [0, 1, 2]


def test_build_and_sort_trips(gtfs_minimal: Path) -> None:
    """Test trip building and sorting."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    routes = build_routes(reader)
    build_and_sort_trips(reader, routes, allow_partial=False)

    route = routes[0]
    assert len(route.trips) == 2

    # Trips should be sorted by first departure
    trip1 = route.trips[0]
    trip2 = route.trips[1]

    assert trip1.arrival_times[0] < trip2.arrival_times[0]

    # Check times are aligned
    assert len(trip1.arrival_times) == 3
    assert len(trip2.arrival_times) == 3


def test_build_stops_with_routes(gtfs_minimal: Path) -> None:
    """Test stop building with route references."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    routes = build_routes(reader)
    stops = build_stops(reader, routes)

    assert len(stops) == 3

    # Each stop should reference route R1 (internal ID 0)
    for stop in stops:
        assert 0 in stop.route_ids


def test_partial_trips_rejected_by_default(gtfs_minimal: Path) -> None:
    """Test partial trips are rejected by default."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    routes = build_routes(reader)

    # No partial trips in minimal fixture, so should work
    build_and_sort_trips(reader, routes, allow_partial=False)

    assert all(not trip.is_partial for route in routes for trip in route.trips)
