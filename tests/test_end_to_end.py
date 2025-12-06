"""End-to-end tests."""

from pathlib import Path

from raptor_pipeline import convert, validate
from raptor_pipeline.gtfs.models import ConvertConfig


def test_end_to_end_minimal(gtfs_minimal: Path, tmp_output: Path) -> None:
    """Test complete pipeline on minimal fixture."""
    # Convert
    manifest = convert(
        str(gtfs_minimal),
        str(tmp_output),
        ConvertConfig(
            input_path=str(gtfs_minimal),
            output_path=str(tmp_output),
            format="binary",
        ),
    )

    # Check manifest
    assert manifest.schema_version == 1
    assert manifest.stats["stops"] == 3
    assert manifest.stats["routes"] == 1
    assert manifest.stats["trips"] == 2

    # Check files exist
    assert (tmp_output / "routes.bin").exists()
    assert (tmp_output / "stops.bin").exists()
    assert (tmp_output / "index.bin").exists()
    assert (tmp_output / "manifest.json").exists()

    # Validate
    report = validate(str(tmp_output))
    assert report.valid
    assert len(report.errors) == 0


def test_end_to_end_branching(gtfs_branching: Path, tmp_output: Path) -> None:
    """Test complete pipeline on branching fixture."""
    manifest = convert(
        str(gtfs_branching),
        str(tmp_output),
    )

    assert manifest.stats["routes"] == 2
    assert manifest.stats["trips"] == 2

    report = validate(str(tmp_output))
    assert report.valid


def test_end_to_end_with_json(gtfs_minimal: Path, tmp_output: Path) -> None:
    """Test pipeline with JSON debug output."""
    manifest = convert(
        str(gtfs_minimal),
        str(tmp_output),
        ConvertConfig(
            input_path=str(gtfs_minimal),
            output_path=str(tmp_output),
            format="both",
            debug_json=True,
        ),
    )

    # Should have both binary and JSON
    assert (tmp_output / "routes.bin").exists()
    assert (tmp_output / "routes.json").exists()
    assert (tmp_output / "stops.json").exists()
    assert (tmp_output / "index.json").exists()

    # Checksums should include all files
    assert "routes.bin" in manifest.outputs
    assert "routes.json" in manifest.outputs


def test_end_to_end_with_transfers(gtfs_minimal: Path, tmp_output: Path) -> None:
    """Test pipeline with generated transfers."""
    manifest = convert(
        str(gtfs_minimal),
        str(tmp_output),
        ConvertConfig(
            input_path=str(gtfs_minimal),
            output_path=str(tmp_output),
            gen_transfers=True,
            transfer_cutoff=10000,  # Large cutoff to ensure some are generated
        ),
    )

    # Should have more transfers than the 4 explicit ones
    assert manifest.stats["transfers"] >= 4

    report = validate(str(tmp_output))
    assert report.valid
