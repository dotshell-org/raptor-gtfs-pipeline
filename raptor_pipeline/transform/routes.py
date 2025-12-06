"""Route transformation and canonical stop sequence inference."""

import logging
from collections import Counter

from raptor_pipeline.gtfs.models import RouteData
from raptor_pipeline.gtfs.reader import GTFSReader

logger = logging.getLogger(__name__)


def build_routes(reader: GTFSReader) -> list[RouteData]:
    """Build RouteData with canonical stop sequences from GTFS trips."""
    logger.info("Building routes with canonical stop sequences")

    # Group trips by route and direction
    trips_by_route_dir: dict[tuple[str, int], list[str]] = {}
    for trip in reader.trips:
        key = (trip.route_id, trip.direction_id)
        if key not in trips_by_route_dir:
            trips_by_route_dir[key] = []
        trips_by_route_dir[key].append(trip.trip_id)

    # Build stop sequences per trip
    stop_sequences: dict[str, list[str]] = {}
    for st in reader.stop_times:
        if st.trip_id not in stop_sequences:
            stop_sequences[st.trip_id] = []
        stop_sequences[st.trip_id].append(st.stop_id)

    routes: list[RouteData] = []

    for (route_id, direction_id), trip_ids in sorted(trips_by_route_dir.items()):
        route_id_internal = reader.get_internal_route_id(route_id)

        # Collect all stop sequences for this route-direction
        sequences_for_route: list[tuple[str, ...]] = []
        for trip_id in trip_ids:
            if trip_id in stop_sequences:
                seq = tuple(stop_sequences[trip_id])
                sequences_for_route.append(seq)

        if not sequences_for_route:
            logger.warning(
                f"Route {route_id} direction {direction_id} has no stop sequences, skipping"
            )
            continue

        # Find canonical sequence by majority
        canonical_seq = _find_canonical_sequence(
            sequences_for_route, f"{route_id}_dir{direction_id}"
        )

        # Convert to internal IDs
        canonical_stop_ids = [reader.get_internal_stop_id(stop_id) for stop_id in canonical_seq]

        route_data = RouteData(
            route_id_internal=route_id_internal,
            route_id_gtfs=route_id,
            stop_ids=canonical_stop_ids,
            trips=[],  # Filled later
        )
        routes.append(route_data)

    logger.info(f"Built {len(routes)} routes")
    return routes


def _find_canonical_sequence(sequences: list[tuple[str, ...]], route_id: str) -> tuple[str, ...]:
    """Find canonical stop sequence by majority vote, with lexicographic tiebreaker."""
    if not sequences:
        raise ValueError(f"Route {route_id} has no sequences")

    # Count occurrences
    counter = Counter(sequences)
    most_common = counter.most_common()

    canonical = most_common[0][0]
    canonical_count = most_common[0][1]

    # Check if there's a tie
    tied_sequences = [seq for seq, count in most_common if count == canonical_count]

    if len(tied_sequences) > 1:
        # Use lexicographic order as deterministic tiebreaker
        logger.warning(
            f"Route {route_id} has {len(tied_sequences)} sequences with equal frequency "
            f"({canonical_count} trips). Using lexicographic order as tiebreaker."
        )
        canonical = min(tied_sequences)

    return canonical
