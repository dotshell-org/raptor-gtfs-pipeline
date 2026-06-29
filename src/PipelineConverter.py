import hashlib
import json
import logging
import platform
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from src.gtfs.CalendarAnalyzer import CalendarAnalyzer
from src.gtfs.GTFSReader import GTFSReader
from src.gtfs.models.ConvertConfig import ConvertConfig
from src.gtfs.models.Manifest import Manifest
from src.gtfs.models.RouteData import RouteData
from src.gtfs.models.ServicePeriod import ServicePeriod
from src.optimization.NetworkIndexBuilder import NetworkIndexBuilder
from src.output.BinarySerializer import BinarySerializer
from src.output.JsonSerializer import JsonSerializer
from src.transform.RouteBuilder import RouteBuilder
from src.transform.StopBuilder import StopBuilder
from src.transform.TransferBuilder import TransferBuilder
from src.transform.TripBuilder import TripBuilder
from src.Version import Version

logger = logging.getLogger(__name__)


class PipelineConverter:
    """Public API for GTFS to RAPTOR conversion pipeline."""

    @staticmethod
    def convert(
        input_path: str,
        output_path: str,
        config: ConvertConfig | None = None,
        period_analyzer: Callable[[GTFSReader], list[ServicePeriod]] | None = None,
    ) -> Manifest:
        """
        Convert GTFS data to RAPTOR binary format.

        Args:
            input_path: Path to GTFS directory
            output_path: Path to output directory
            config: Optional conversion configuration
            period_analyzer: Optional callable to compute service periods from the
                             GTFSReader. Receives the reader and returns a list of
                             ServicePeriod. If None, CalendarAnalyzer is used.

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

        # Check if we should split by service periods
        periods: list[ServicePeriod] | None = None
        if config.split_by_periods:
            if period_analyzer:
                logger.info("Using custom period analyzer")
                periods = period_analyzer(reader)
            else:
                periods = CalendarAnalyzer.analyze_service_periods(reader)

            if not periods:
                logger.warning(
                    "split_by_periods enabled but no calendar data found, "
                    "generating single output"
                )
                periods = None

        # Build routes and trips ONCE (optimization for period splitting)
        logger.info("Building routes and trips from GTFS data...")
        routes = RouteBuilder.build_routes(reader)
        TripBuilder.build_and_sort_trips(reader, routes, allow_partial=config.allow_partial_trips)
        total_trips = sum(len(r.trips) for r in routes)
        logger.info(f"Built {len(routes)} routes with {total_trips} trips total")

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
                period_trip_ids = CalendarAnalyzer.get_trips_for_period(reader, period)
                logger.info(f"Found {len(period_trip_ids)} trips for period {period.name}")

                # Filter routes (reuse pre-built routes)
                filtered_routes = PipelineConverter._filter_routes_by_trips(
                    routes, period_trip_ids
                )
                logger.info(
                    f"After filtering: {len(filtered_routes)} routes with trips in this period"
                )

                # Generate output for this period
                manifest = PipelineConverter._write_period_output(
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
            return PipelineConverter._write_period_output(
                reader=reader,
                routes=routes,
                output_path=Path(output_path),
                config=config,
                start_time=start_time,
                input_path=input_path,
                period_name=None,
            )

    @staticmethod
    def _write_period_output(
        reader: GTFSReader,
        routes: list[RouteData],
        output_path: Path,
        config: ConvertConfig,
        start_time: datetime,
        input_path: str,
        period_name: str | None,
    ) -> Manifest:
        """
        Write output files for a specific period (or all data).
        """
        # Build stops from the filtered routes
        stops = StopBuilder.build_stops(reader, routes)
        TransferBuilder.build_transfers(
            reader,
            stops,
            gen_transfers=config.gen_transfers,
            speed_walk=config.speed_walk,
            transfer_cutoff=config.transfer_cutoff,
        )

        # Build index
        index = NetworkIndexBuilder.build_network_index(routes, stops)

        # Write outputs
        output_dir = output_path
        files_written: dict[str, str] = {}

        if config.format in ("binary", "both"):
            BinarySerializer.write_binary_files(
                output_dir, routes, stops, index, Version.SCHEMA_VERSION, config.compression
            )
            files_written.update({
                "routes.bin": str(output_dir / "routes.bin"),
                "stops.bin": str(output_dir / "stops.bin"),
                "index.bin": str(output_dir / "index.bin")
            })

        if config.format in ("json", "both") or config.debug_json:
            JsonSerializer.write_json_files(output_dir, routes, stops, index)
            files_written.update({
                "routes.json": str(output_dir / "routes.json"),
                "stops.json": str(output_dir / "stops.json"),
                "index.json": str(output_dir / "index.json")
            })

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
            schema_version=Version.SCHEMA_VERSION,
            tool_version=Version.VERSION,
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
            print(f"Period '{period_name}' completed")
        else:
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            print(f"Conversion completed in {elapsed:.2f}s")

        return manifest

    @staticmethod
    def _filter_routes_by_trips(
        routes: list[RouteData], period_trip_ids: set[str]
    ) -> list[RouteData]:
        """
        Filter routes to only include trips that belong to the specified period.
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
