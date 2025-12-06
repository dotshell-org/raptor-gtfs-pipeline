"""Indexing structures for fast lookups."""

import logging

from raptor_pipeline.gtfs.models import NetworkIndex, RouteData, StopData

logger = logging.getLogger(__name__)


def build_network_index(routes: list[RouteData], stops: list[StopData]) -> NetworkIndex:
    """Build network index with stop-to-routes mapping and offsets."""
    logger.info("Building network index")

    index = NetworkIndex()

    # Build stop_to_routes from stop data
    for stop in stops:
        if stop.route_ids:
            index.stop_to_routes[stop.stop_id_internal] = sorted(stop.route_ids)

    # Offsets will be filled during binary writing
    # Initialize empty dictionaries
    index.route_offsets = {}
    index.stop_offsets = {}

    logger.info(f"Built index with {len(index.stop_to_routes)} stop-to-route mappings")

    return index
