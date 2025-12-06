"""GTFS data validator."""

import logging
from typing import Any

from raptor_pipeline.gtfs.models import ValidationReport
from raptor_pipeline.gtfs.reader import GTFSReader

logger = logging.getLogger(__name__)


class GTFSValidator:
    """Validate GTFS data for consistency and correctness."""

    def __init__(self, reader: GTFSReader) -> None:
        """Initialize validator with GTFS reader."""
        self.reader = reader
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def validate(self) -> ValidationReport:
        """Run all validation checks."""
        logger.info("Validating GTFS data")

        self._validate_stops()
        self._validate_routes()
        self._validate_trips()
        self._validate_stop_times()
        self._validate_transfers()

        valid = len(self.errors) == 0

        stats = {
            "stops": len(self.reader.stops),
            "routes": len(self.reader.routes),
            "trips": len(self.reader.trips),
            "stop_times": len(self.reader.stop_times),
            "transfers": len(self.reader.transfers),
        }

        report = ValidationReport(
            valid=valid,
            errors=self.errors.copy(),
            warnings=self.warnings.copy(),
            stats=stats,
        )

        if not valid:
            logger.error(f"Validation failed with {len(self.errors)} errors")
        elif self.warnings:
            logger.warning(f"Validation passed with {len(self.warnings)} warnings")
        else:
            logger.info("Validation passed")

        return report

    def _validate_stops(self) -> None:
        """Validate stops have valid coordinates."""
        for stop in self.reader.stops:
            if not (-90 <= stop.lat <= 90):
                self.errors.append(f"Stop {stop.stop_id} has invalid latitude: {stop.lat}")
            if not (-180 <= stop.lon <= 180):
                self.errors.append(f"Stop {stop.stop_id} has invalid longitude: {stop.lon}")
            if not stop.name:
                self.warnings.append(f"Stop {stop.stop_id} has empty name")

    def _validate_routes(self) -> None:
        """Validate routes."""
        if not self.reader.routes:
            self.errors.append("No routes found in GTFS data")

    def _validate_trips(self) -> None:
        """Validate trips reference valid routes."""
        route_ids = {route.route_id for route in self.reader.routes}

        for trip in self.reader.trips:
            if trip.route_id not in route_ids:
                self.errors.append(
                    f"Trip {trip.trip_id} references non-existent route {trip.route_id}"
                )

    def _validate_stop_times(self) -> None:
        """Validate stop_times are ordered and reference valid stops/trips."""
        stop_ids = {stop.stop_id for stop in self.reader.stops}
        trip_ids = {trip.trip_id for trip in self.reader.trips}

        # Group by trip
        trip_stop_times: dict[str, list[Any]] = {}
        for st in self.reader.stop_times:
            if st.trip_id not in trip_stop_times:
                trip_stop_times[st.trip_id] = []
            trip_stop_times[st.trip_id].append(st)

        for trip_id, stop_times in trip_stop_times.items():
            if trip_id not in trip_ids:
                self.errors.append(f"Stop times reference non-existent trip {trip_id}")
                continue

            if not stop_times:
                self.errors.append(f"Trip {trip_id} has no stop times")
                continue

            # Check stop_sequence is ordered
            sequences = [st.stop_sequence for st in stop_times]
            sorted_sequences = sorted(sequences)
            if sequences != sorted_sequences:
                self.errors.append(
                    f"Trip {trip_id} has unordered stop_sequence values: {sequences}"
                )

            # Check times are monotonically increasing
            prev_time = -1
            for st in stop_times:
                if st.stop_id not in stop_ids:
                    self.errors.append(
                        f"Stop time for trip {trip_id} references non-existent stop {st.stop_id}"
                    )

                if st.arrival_time < prev_time:
                    self.warnings.append(
                        f"Trip {trip_id} has non-increasing times at stop {st.stop_id}: "
                        f"{prev_time} -> {st.arrival_time}"
                    )

                prev_time = st.departure_time

            # Check first and last times are present
            if stop_times[0].arrival_time < 0:
                self.errors.append(f"Trip {trip_id} missing first arrival time")
            if stop_times[-1].departure_time < 0:
                self.errors.append(f"Trip {trip_id} missing last departure time")

    def _validate_transfers(self) -> None:
        """Validate transfers reference valid stops and have reasonable times."""
        stop_ids = {stop.stop_id for stop in self.reader.stops}

        for transfer in self.reader.transfers:
            if transfer.from_stop_id not in stop_ids:
                self.errors.append(
                    f"Transfer references non-existent from_stop {transfer.from_stop_id}"
                )
            if transfer.to_stop_id not in stop_ids:
                self.errors.append(
                    f"Transfer references non-existent to_stop {transfer.to_stop_id}"
                )

            if transfer.min_transfer_time < 0:
                self.warnings.append(
                    f"Transfer {transfer.from_stop_id}->{transfer.to_stop_id} "
                    f"has negative time: {transfer.min_transfer_time}"
                )
            elif transfer.min_transfer_time > 3600:
                self.warnings.append(
                    f"Transfer {transfer.from_stop_id}->{transfer.to_stop_id} "
                    f"has excessive time: {transfer.min_transfer_time}s"
                )
