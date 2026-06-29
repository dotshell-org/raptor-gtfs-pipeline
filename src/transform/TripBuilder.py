import logging
import math

import numpy as np

from src.gtfs.GTFSReader import GTFSReader
from src.gtfs.models.RouteData import RouteData
from src.gtfs.models.TripData import TripData

logger = logging.getLogger(__name__)


class TripBuilder:
    """Trip transformation and sorting — vectorized via Pandas pivot + Numpy."""

    @staticmethod
    def build_and_sort_trips(
        reader: GTFSReader, routes: list[RouteData], allow_partial: bool = False
    ) -> None:
        """Build TripData for each route using pivot_table; sort by departure time."""
        logger.info("Building and sorting trips")

        st_df = reader.stop_times_df
        trips_df = reader.trips_df

        # Pre-index: route_id → list of (trip_id_gtfs, trip_id_internal)
        # Optimization: group by route_id once using Pandas
        route_groups = trips_df.groupby("route_id")

        total_trips = 0

        for route in routes:
            route_id_gtfs = route.route_id_gtfs
            canonical_stops = route.stop_ids  # list[int] of stop_id_internal

            try:
                route_trips = route_groups.get_group(route_id_gtfs)
            except KeyError:
                continue

            trip_internal_ids = route_trips["trip_id_internal"].tolist()
            # Map trip_id_internal → trip_id_gtfs for warning messages
            int_to_gtfs = dict(zip(route_trips["trip_id_internal"], route_trips["trip_id"]))

            # Filter stop_times to this route's trips
            route_st = st_df[st_df["trip_id_internal"].isin(trip_internal_ids)]
            if route_st.empty:
                continue

            # Pivot: rows = trip_id_internal, cols = stop_id_internal, values = arrival_time
            pivot = route_st.pivot_table(
                index="trip_id_internal",
                columns="stop_id_internal",
                values="arrival_time",
                aggfunc="first",
            )

            # Reindex to canonical stop order; missing stops become NaN → np.inf
            pivot = pivot.reindex(columns=canonical_stops)
            matrix = pivot.to_numpy(dtype=float).copy()  # (n_trips, n_stops)
            matrix[np.isnan(matrix)] = np.inf

            trip_data_list: list[tuple[float, TripData]] = []

            for i, trip_id_internal in enumerate(pivot.index):
                arrival_times: list[float] = matrix[i].tolist()
                is_partial = any(math.isinf(t) for t in arrival_times)

                if is_partial and not allow_partial:
                    trip_gtfs = int_to_gtfs.get(int(trip_id_internal), str(trip_id_internal))
                    logger.debug(
                        f"Trip {trip_gtfs} is partial (missing stops), rejecting. "
                        "Use --allow-partial-trips to include."
                    )
                    continue

                first_time = arrival_times[0] if arrival_times else math.inf
                trip_data = TripData(
                    trip_id_internal=int(trip_id_internal),
                    trip_id_gtfs=int_to_gtfs.get(int(trip_id_internal), ""),
                    arrival_times=arrival_times,
                    is_partial=is_partial,
                )
                trip_data_list.append((first_time, trip_data))

            trip_data_list.sort(key=lambda x: x[0])
            route.trips = [td for _, td in trip_data_list]
            total_trips += len(route.trips)

            logger.debug(f"Route {route_id_gtfs}: {len(route.trips)} trips")

        logger.info(f"Built {total_trips} trips across {len(routes)} routes")
