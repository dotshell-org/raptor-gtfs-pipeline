import logging
from collections import Counter

import pandas as pd

from src.gtfs.GTFSReader import GTFSReader
from src.gtfs.models.RouteData import RouteData

logger = logging.getLogger(__name__)


class RouteBuilder:
    """Route transformation and canonical stop sequence inference."""

    @staticmethod
    def build_routes(reader: GTFSReader) -> list[RouteData]:
        """Build RouteData with canonical stop sequences from GTFS trips."""
        logger.info("Building routes with canonical stop sequences")

        st_df = reader.stop_times_df
        trips_df = reader.trips_df

        # Vectorized groupby: trip_id → ordered tuple of stop_ids
        trip_sequences: dict[str, tuple[str, ...]] = (
            st_df.groupby("trip_id")["stop_id"]
            .apply(tuple)
            .to_dict()  # type: ignore[assignment]
        )

        # Pre-build route name lookup (avoid O(n) scan per route)
        route_name_lookup: dict[str, str] = {
            r.route_id: r.route_short_name or r.route_long_name
            for r in reader.routes
        }

        # Group trips by (route_id, direction_id) using DataFrame groupby
        trips_by_route_dir = (
            trips_df.groupby(["route_id", "direction_id"])["trip_id"]
            .apply(list)
            .to_dict()
        )

        routes: list[RouteData] = []

        for (route_id, direction_id), trip_ids in sorted(trips_by_route_dir.items()):
            route_id_internal = reader.get_internal_route_id(route_id)

            sequences_for_route: list[tuple[str, ...]] = [
                trip_sequences[tid] for tid in trip_ids if tid in trip_sequences
            ]

            if not sequences_for_route:
                logger.warning(
                    f"Route {route_id} direction {direction_id} "
                    "has no stop sequences, skipping"
                )
                continue

            canonical_seq = RouteBuilder._find_canonical_sequence(
                sequences_for_route, f"{route_id}_dir{direction_id}"
            )

            canonical_stop_ids = [
                reader.get_internal_stop_id(stop_id) for stop_id in canonical_seq
            ]
            route_name = route_name_lookup.get(route_id, "")

            routes.append(RouteData(
                route_id_internal=route_id_internal,
                route_id_gtfs=route_id,
                route_name=route_name,
                stop_ids=canonical_stop_ids,
                trips=[],
            ))

        logger.info(f"Built {len(routes)} routes")
        return routes

    @staticmethod
    def _find_canonical_sequence(
        sequences: list[tuple[str, ...]], route_id: str
    ) -> tuple[str, ...]:
        """Find canonical stop sequence by majority vote, with lexicographic tiebreaker."""
        if not sequences:
            raise ValueError(f"Route {route_id} has no sequences")

        counter = Counter(sequences)
        most_common = counter.most_common()

        canonical = most_common[0][0]
        canonical_count = most_common[0][1]

        tied_sequences = [seq for seq, count in most_common if count == canonical_count]

        if len(tied_sequences) > 1:
            logger.debug(
                f"Route {route_id} has {len(tied_sequences)} sequences with equal frequency "
                f"({canonical_count} trips). Using lexicographic order as tiebreaker."
            )
            canonical = min(tied_sequences)

        return canonical

    @staticmethod
    def _get_route_name(reader: GTFSReader, route_id: str) -> str:
        """Get route name from GTFS data, preferring short_name over long_name."""
        for route in reader.routes:
            if route.route_id == route_id:
                if route.route_short_name:
                    return route.route_short_name
                return route.route_long_name
        return ""

    @staticmethod
    def _build_stop_sequences_from_df(
        st_df: pd.DataFrame,
    ) -> dict[str, tuple[str, ...]]:
        """Build trip_id → stop_id tuple mapping from stop_times DataFrame."""
        return (
            st_df.groupby("trip_id")["stop_id"]
            .apply(tuple)
            .to_dict()  # type: ignore[return-value]
        )
