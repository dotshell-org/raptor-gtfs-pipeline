"""Trip transformation and sorting."""

import logging
import math
from typing import Any

from raptor_pipeline.gtfs.models import RouteData, TripData
from raptor_pipeline.gtfs.reader import GTFSReader

logger = logging.getLogger(__name__)


def build_and_sort_trips(
    reader: GTFSReader, routes: list[RouteData], allow_partial: bool = False
) -> None:
    """Build TripData for each route, sort by departure time, align to canonical sequence."""
    logger.info("Building and sorting trips")

    # Group stop_times by trip
    stop_times_by_trip: dict[str, list[Any]] = {}
    for st in reader.stop_times:
        if st.trip_id not in stop_times_by_trip:
            stop_times_by_trip[st.trip_id] = []
        stop_times_by_trip[st.trip_id].append(st)

    # Process each route
    for route in routes:
        route_id_gtfs = route.route_id_gtfs
        canonical_stops = route.stop_ids

        # Find trips for this route
        route_trips = [trip for trip in reader.trips if trip.route_id == route_id_gtfs]

        trip_data_list: list[tuple[int, TripData]] = []

        for trip in route_trips:
            trip_id = trip.trip_id
            trip_id_internal = reader.get_internal_trip_id(trip_id)

            if trip_id not in stop_times_by_trip:
                logger.warning(f"Trip {trip_id} has no stop times, skipping")
                continue

            stop_times = stop_times_by_trip[trip_id]

            # Build mapping from stop_id to arrival_time
            stop_time_map: dict[int, int] = {}
            for st in stop_times:
                stop_id_internal = reader.get_internal_stop_id(st.stop_id)
                stop_time_map[stop_id_internal] = st.arrival_time

            # Align to canonical sequence
            aligned_times: list[int] = []
            is_partial = False

            for stop_id in canonical_stops:
                if stop_id in stop_time_map:
                    aligned_times.append(stop_time_map[stop_id])
                else:
                    aligned_times.append(math.inf)  # type: ignore
                    is_partial = True

            # Reject partial trips unless allowed
            if is_partial and not allow_partial:
                logger.warning(
                    f"Trip {trip_id} is partial (missing stops), rejecting. "
                    f"Use --allow-partial-trips to include."
                )
                continue

            # Get first departure time for sorting
            first_time = aligned_times[0] if aligned_times else math.inf

            trip_data = TripData(
                trip_id_internal=trip_id_internal,
                trip_id_gtfs=trip_id,
                arrival_times=aligned_times,
                is_partial=is_partial,
            )

            trip_data_list.append((first_time, trip_data))  # type: ignore

        # Sort by first departure time
        trip_data_list.sort(key=lambda x: x[0])
        route.trips = [td for _, td in trip_data_list]

        logger.debug(f"Route {route_id_gtfs}: {len(route.trips)} trips")

    total_trips = sum(len(route.trips) for route in routes)
    logger.info(f"Built {total_trips} trips across {len(routes)} routes")
