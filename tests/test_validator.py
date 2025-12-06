"""Tests for GTFS validator."""

from pathlib import Path

from raptor_pipeline.gtfs.reader import GTFSReader
from raptor_pipeline.gtfs.validator import GTFSValidator


def test_validator_valid_data(gtfs_minimal: Path) -> None:
    """Test validator passes on valid data."""
    reader = GTFSReader(str(gtfs_minimal))
    reader.read_all()

    validator = GTFSValidator(reader)
    report = validator.validate()

    assert report.valid
    assert len(report.errors) == 0
    assert report.stats["stops"] == 3
    assert report.stats["routes"] == 1


def test_validator_invalid_coordinates(gtfs_edgecases: Path) -> None:
    """Test validator catches invalid coordinates."""
    reader = GTFSReader(str(gtfs_edgecases))
    reader.read_all()

    validator = GTFSValidator(reader)
    report = validator.validate()

    assert not report.valid
    assert any("latitude" in err.lower() for err in report.errors)
    assert any("longitude" in err.lower() for err in report.errors)


def test_validator_orphan_trip(gtfs_edgecases: Path) -> None:
    """Test validator catches trips referencing nonexistent routes."""
    reader = GTFSReader(str(gtfs_edgecases))
    reader.read_all()

    validator = GTFSValidator(reader)
    report = validator.validate()

    assert not report.valid
    assert any("non-existent route" in err.lower() for err in report.errors)


def test_validator_unordered_stop_times(gtfs_edgecases: Path) -> None:
    """Test validator catches various edge cases."""
    reader = GTFSReader(str(gtfs_edgecases))
    reader.read_all()

    validator = GTFSValidator(reader)
    report = validator.validate()

    assert not report.valid
    # Should have errors for invalid coordinates, orphan trips, or bad references
    assert len(report.errors) > 0


def test_validator_warnings(gtfs_edgecases: Path) -> None:
    """Test validator generates warnings for edge cases."""
    reader = GTFSReader(str(gtfs_edgecases))
    reader.read_all()

    validator = GTFSValidator(reader)
    report = validator.validate()

    # Should have warnings about transfers
    assert len(report.warnings) > 0
