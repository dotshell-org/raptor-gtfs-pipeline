"""Tests for indexing."""

from pathlib import Path

from raptor_pipeline.gtfs.reader import GTFSReader
from raptor_pipeline.optimization.indexing import build_network_index
from raptor_pipeline.transform.routes import build_routes
from raptor_pipeline.transform.stops import build_stops
from raptor_pipeline.transform.trips import build_and_sort_trips


def test_build_network_index(gtfs_minimal: Path) -> None:
    """Test building network index."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    routes = build_routes(reader)
    build_and_sort_trips(reader, routes)
    stops = build_stops(reader, routes)

    index = build_network_index(routes, stops)

    # Should have stop_to_routes mapping
    assert len(index.stop_to_routes) == 3

    # Each stop should map to route 0
    for stop_id in range(3):
        assert stop_id in index.stop_to_routes
        assert 0 in index.stop_to_routes[stop_id]


def test_stop_to_routes_sorted(gtfs_minimal: Path) -> None:
    """Test stop_to_routes mapping is sorted."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    routes = build_routes(reader)
    build_and_sort_trips(reader, routes)
    stops = build_stops(reader, routes)

    index = build_network_index(routes, stops)

    for stop_id, route_ids in index.stop_to_routes.items():
        assert route_ids == sorted(route_ids)


def test_index_with_multiple_routes(gtfs_branching: Path) -> None:
    """Test indexing with multiple routes."""
    reader = GTFSReader(str(gtfs_branching))
    reader.read_all()

    routes = build_routes(reader)
    build_and_sort_trips(reader, routes)
    stops = build_stops(reader, routes)

    index = build_network_index(routes, stops)

    # S2 should be on both routes
    s2_internal = reader.get_internal_stop_id("S2")
    assert len(index.stop_to_routes[s2_internal]) == 2
