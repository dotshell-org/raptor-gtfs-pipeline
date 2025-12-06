"""Public API for raptor-gtfs-pipeline."""

import hashlib
import json
import logging
import platform
from datetime import UTC, datetime
from pathlib import Path

from raptor_pipeline.gtfs.models import ConvertConfig, Manifest, ValidationReport
from raptor_pipeline.gtfs.reader import GTFSReader
from raptor_pipeline.gtfs.validator import GTFSValidator
from raptor_pipeline.optimization.indexing import build_network_index
from raptor_pipeline.output.binary import validate_binary_files, write_binary_files
from raptor_pipeline.output.json import write_json_files
from raptor_pipeline.transform.routes import build_routes
from raptor_pipeline.transform.stops import build_stops
from raptor_pipeline.transform.transfers import build_transfers
from raptor_pipeline.transform.trips import build_and_sort_trips
from raptor_pipeline.version import SCHEMA_VERSION, VERSION

logger = logging.getLogger(__name__)


def convert(
    input_path: str,
    output_path: str,
    config: ConvertConfig | None = None,
) -> Manifest:
    """
    Convert GTFS data to RAPTOR binary format.

    Args:
        input_path: Path to GTFS directory
        output_path: Path to output directory
        config: Optional conversion configuration

    Returns:
        Manifest with build metadata
    """
    if config is None:
        config = ConvertConfig(input_path=input_path, output_path=output_path)

    logger.info(f"Starting conversion: {input_path} -> {output_path}")
    start_time = datetime.now(UTC)

    # Read GTFS
    reader = GTFSReader(input_path)
    reader.read_all()

    # Validate
    validator = GTFSValidator(reader)
    validation_report = validator.validate()
    if not validation_report.valid:
        raise ValueError(f"GTFS validation failed with {len(validation_report.errors)} errors")

    # Transform
    routes = build_routes(reader)
    build_and_sort_trips(reader, routes, allow_partial=config.allow_partial_trips)
    stops = build_stops(reader, routes)
    build_transfers(
        reader,
        stops,
        gen_transfers=config.gen_transfers,
        speed_walk=config.speed_walk,
        transfer_cutoff=config.transfer_cutoff,
    )

    # Build index
    index = build_network_index(routes, stops)

    # Write outputs
    output_dir = Path(output_path)
    files_written: dict[str, str] = {}

    if config.format in ("binary", "both"):
        binary_files = write_binary_files(
            output_dir, routes, stops, index, SCHEMA_VERSION, config.compression
        )
        files_written.update(binary_files)

    if config.format in ("json", "both") or config.debug_json:
        json_files = write_json_files(output_dir, routes, stops, index)
        files_written.update(json_files)

    # Compute checksums
    checksums = {}
    for filename, filepath in files_written.items():
        with open(filepath, "rb") as f:
            checksums[filename] = hashlib.sha256(f.read()).hexdigest()

    # Create manifest
    stats = {
        "stops": len(stops),
        "routes": len(routes),
        "trips": sum(len(route.trips) for route in routes),
        "stop_times": sum(len(route.stop_ids) * len(route.trips) for route in routes),
        "transfers": sum(len(stop.transfers) for stop in stops),
    }

    manifest = Manifest(
        schema_version=SCHEMA_VERSION,
        tool_version=VERSION,
        created_at_iso=start_time.isoformat(),
        inputs={"gtfs_path": input_path},
        outputs=checksums,
        stats=stats,
        build={
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    )

    # Write manifest
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "schema_version": manifest.schema_version,
                "tool_version": manifest.tool_version,
                "created_at": manifest.created_at_iso,
                "inputs": manifest.inputs,
                "outputs": manifest.outputs,
                "stats": manifest.stats,
                "build": manifest.build,
            },
            f,
            indent=2,
            sort_keys=True,
        )

    logger.info(f"Wrote manifest to {manifest_path}")

    elapsed = (datetime.now(UTC) - start_time).total_seconds()
    logger.info(f"Conversion completed in {elapsed:.2f}s")

    return manifest


def validate(output_path: str) -> ValidationReport:
    """
    Validate RAPTOR binary output.

    Args:
        output_path: Path to output directory containing binary files

    Returns:
        ValidationReport with results
    """
    logger.info(f"Validating output: {output_path}")

    output_dir = Path(output_path)
    errors: list[str] = []
    warnings: list[str] = []

    # Check required files exist
    required_files = ["routes.bin", "stops.bin", "index.bin", "manifest.json"]
    for filename in required_files:
        if not (output_dir / filename).exists():
            errors.append(f"Required file missing: {filename}")

    if errors:
        return ValidationReport(valid=False, errors=errors, warnings=warnings)

    # Validate binary files
    try:
        stats = validate_binary_files(output_dir)
    except Exception as e:
        errors.append(f"Binary validation failed: {e}")
        return ValidationReport(valid=False, errors=errors, warnings=warnings)

    # Validate manifest
    manifest_path = output_dir / "manifest.json"
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest_data = json.load(f)

        # Check manifest has required fields
        required_manifest_fields = [
            "schema_version",
            "tool_version",
            "created_at",
            "outputs",
            "stats",
        ]
        for field in required_manifest_fields:
            if field not in manifest_data:
                warnings.append(f"Manifest missing field: {field}")

        # Verify checksums
        for filename, expected_hash in manifest_data.get("outputs", {}).items():
            filepath = output_dir / filename
            if filepath.exists():
                with open(filepath, "rb") as f:
                    actual_hash = hashlib.sha256(f.read()).hexdigest()
                if actual_hash != expected_hash:
                    errors.append(
                        f"Checksum mismatch for {filename}: "
                        f"expected {expected_hash}, got {actual_hash}"
                    )

    except Exception as e:
        errors.append(f"Manifest validation failed: {e}")

    valid = len(errors) == 0

    if valid:
        logger.info("Validation passed")
    else:
        logger.error(f"Validation failed with {len(errors)} errors")

    return ValidationReport(
        valid=valid,
        errors=errors,
        warnings=warnings,
        stats=stats,
    )
