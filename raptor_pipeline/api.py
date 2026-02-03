"""Public API for raptor-gtfs-pipeline."""

import hashlib
import json
import logging
import platform
from datetime import UTC, datetime
from pathlib import Path

from raptor_pipeline.gtfs.calendar import analyze_service_periods, get_trips_for_period
from raptor_pipeline.gtfs.modes import get_mode_analyzer
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

    # Check if we should split by service periods
    if config.split_by_periods:
        # Use mode-specific analyzer if specified
        mode_analyzer = get_mode_analyzer(config.mode)
        if mode_analyzer:
            logger.info(f"Using {config.mode} mode for period analysis")
            periods = mode_analyzer(reader)
        else:
            periods = analyze_service_periods(reader)
        
        if not periods:
            logger.warning("split_by_periods enabled but no calendar data found, generating single output")
            periods = None
    else:
        periods = None
    
    # Build routes and trips ONCE (optimization for period splitting)
    logger.info("Building routes and trips from GTFS data...")
    routes = build_routes(reader)
    build_and_sort_trips(reader, routes, allow_partial=config.allow_partial_trips)
    logger.info(f"Built {len(routes)} routes with {sum(len(r.trips) for r in routes)} trips total")
    
    # If splitting by periods, generate one folder per period
    if periods:
        manifests = []
        base_output = Path(output_path)
        
        for period in periods:
            logger.info(f"\n{'=' * 60}")
            logger.info(f"Processing period: {period.name}")
            logger.info(f"Description: {period.description}")
            logger.info(f"Services: {len(period.service_ids)}")
            logger.info(f"{'=' * 60}\n")
            
            # Filter trips for this period
            period_trip_ids = get_trips_for_period(reader, period)
            logger.info(f"Found {len(period_trip_ids)} trips for period {period.name}")
            
            # Filter routes (reuse pre-built routes)
            filtered_routes = _filter_routes_by_trips(routes, period_trip_ids)
            logger.info(f"After filtering: {len(filtered_routes)} routes with trips in this period")
            
            # Generate output for this period
            manifest = _write_period_output(
                reader=reader,
                routes=filtered_routes,
                output_path=base_output / period.name,
                config=config,
                start_time=start_time,
                input_path=input_path,
                period_name=period.name,
            )
            manifests.append(manifest)
        
        # Return summary manifest
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Generated {len(manifests)} period folders:")
        for period in periods:
            logger.info(f"  - {period.name}: {period.description}")
        logger.info(f"{'=' * 60}\n")
        
        return manifests[0]  # Return first manifest for backward compatibility
    else:
        # Single output (original behavior)
        return _write_period_output(
            reader=reader,
            routes=routes,
            output_path=Path(output_path),
            config=config,
            start_time=start_time,
            input_path=input_path,
            period_name=None,
        )


def _write_period_output(
    reader: GTFSReader,
    routes: list,
    output_path: Path,
    config: ConvertConfig,
    start_time: datetime,
    input_path: str,
    period_name: str | None,
) -> Manifest:
    """
    Write output files for a specific period (or all data).
    
    Args:
        reader: GTFSReader with loaded data
        routes: Pre-built and filtered RouteData list
        output_path: Output directory path
        config: Conversion configuration
        start_time: Conversion start time
        input_path: Original GTFS input path
        period_name: Name of the period, or None
    
    Returns:
        Manifest with build metadata
    """
    # Build stops from the filtered routes
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
    output_dir = output_path
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
    
    manifest_inputs = {"gtfs_path": input_path}
    if period_name:
        manifest_inputs["period"] = period_name

    manifest = Manifest(
        schema_version=SCHEMA_VERSION,
        tool_version=VERSION,
        created_at_iso=start_time.isoformat(),
        inputs=manifest_inputs,
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
    
    if period_name:
        logger.info(f"Period '{period_name}' completed")
    else:
        elapsed = (datetime.now(UTC) - start_time).total_seconds()
        logger.info(f"Conversion completed in {elapsed:.2f}s")

    return manifest


def _filter_routes_by_trips(routes: list, period_trip_ids: set[str]) -> list:
    """
    Filter routes to only include trips that belong to the specified period.
    
    Args:
        routes: List of RouteData objects
        period_trip_ids: Set of trip IDs to include
    
    Returns:
        Filtered list of RouteData objects with only matching trips
    """
    filtered_routes = []
    
    for route in routes:
        # Filter trips for this route
        filtered_trips = [
            trip for trip in route.trips
            if trip.trip_id_gtfs in period_trip_ids
        ]
        
        # Only include route if it has trips in this period
        if filtered_trips:
            # Create a copy of the route with filtered trips
            from copy import copy
            filtered_route = copy(route)
            filtered_route.trips = filtered_trips
            filtered_routes.append(filtered_route)
    
    return filtered_routes


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
