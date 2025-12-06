"""Tests for GTFS reader."""

from pathlib import Path

import pytest

from raptor_pipeline.gtfs.reader import GTFSReader


def test_reader_basic(gtfs_minimal: Path) -> None:
    """Test basic GTFS reading."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    assert len(reader.stops) == 3
    assert len(reader.routes) == 1
    assert len(reader.trips) == 2
    assert len(reader.stop_times) == 6
    assert len(reader.transfers) == 4


def test_reader_stop_id_mapping(gtfs_minimal: Path) -> None:
    """Test stop ID mapping is stable and deterministic."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    # IDs should be assigned in sorted order
    assert reader.get_internal_stop_id("A") == 0
    assert reader.get_internal_stop_id("B") == 1
    assert reader.get_internal_stop_id("C") == 2


def test_parse_time_normal() -> None:
    """Test time parsing for normal times."""
    assert GTFSReader._parse_time("08:30:45") == 8 * 3600 + 30 * 60 + 45
    assert GTFSReader._parse_time("00:00:00") == 0
    assert GTFSReader._parse_time("23:59:59") == 23 * 3600 + 59 * 60 + 59


def test_parse_time_over_24h() -> None:
    """Test time parsing for times over 24 hours."""
    assert GTFSReader._parse_time("25:30:00") == 25 * 3600 + 30 * 60
    assert GTFSReader._parse_time("48:00:00") == 48 * 3600


def test_reader_missing_file() -> None:
    """Test reader with missing required files."""
    with pytest.raises(ValueError):
        GTFSReader("/nonexistent/path")


def test_reader_stop_times_ordered(gtfs_minimal: Path) -> None:
    """Test stop times are ordered by trip and sequence."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    # Group by trip
    by_trip: dict[str, list[int]] = {}
    for st in reader.stop_times:
        if st.trip_id not in by_trip:
            by_trip[st.trip_id] = []
        by_trip[st.trip_id].append(st.stop_sequence)

    # Each trip should have ordered sequences
    for trip_id, sequences in by_trip.items():
        assert sequences == sorted(sequences), f"Trip {trip_id} has unordered sequences"
